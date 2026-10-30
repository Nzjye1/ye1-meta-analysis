args <- commandArgs(trailingOnly=TRUE)
if (length(args)!=2) stop("Usage: Rscript small_study_diagnostics.R BOUND_STATS_DIR OUTPUT_DIR",call.=FALSE)
folder <- normalizePath(args[1],mustWork=TRUE)
target <- args[2]
script <- sub("^--file=","",grep("^--file=",commandArgs(FALSE),value=TRUE)[1])
if (!file.exists(script)) script <- gsub("~+~"," ",script,fixed=TRUE)
root <- normalizePath(file.path(dirname(script),".."),mustWork=TRUE)
source(file.path(root,"scripts","runtime_library.R"))
configure_meta_library(root)
if (!requireNamespace("metafor",quietly=TRUE)) stop("metafor unavailable",call.=FALSE)
d <- read.csv(file.path(folder,"study_effects_trace.csv"),check.names=FALSE,fileEncoding="UTF-8-BOM")
p <- read.csv(file.path(folder,"pooled_result.csv"),check.names=FALSE,fileEncoding="UTF-8-BOM")
if (nrow(p)!=1 || !all(c("study_id","analysis_effect","analysis_variance") %in% names(d)) ||
    !all(c("effect_type","model","tau_method","test","alpha","k","pooled","ci_lower","ci_upper") %in% names(p)))
  stop("bound statistics schema incomplete",call.=FALSE)
if (nrow(d)<3 || p$k!=nrow(d) || anyDuplicated(d$study_id) ||
    any(!is.finite(d$analysis_effect)) || any(!is.finite(d$analysis_variance) | d$analysis_variance<=0))
  stop("requires at least three independent effects with finite positive variances",call.=FALSE)
if (!(p$effect_type %in% c("RR","OR","HR","MD","SMD")) || p$test!="z" ||
    !(p$model %in% c("FE","RE")) ||
    (p$model=="FE" && p$tau_method!="NONE") || (p$model=="RE" && p$tau_method!="REML") ||
    !is.finite(p$alpha) || p$alpha<=0 || p$alpha>=0.5)
  stop("unsupported effect/model/test/alpha contract",call.=FALSE)
fit <- metafor::rma.uni(yi=d$analysis_effect,vi=d$analysis_variance,
  method=if(p$model=="FE") "FE" else "REML",test="z",level=100*(1-p$alpha),slab=d$study_id)
back <- if(p$effect_type %in% c("RR","OR","HR")) exp else identity
close <- function(x,y) is.finite(x) && is.finite(y) && abs(x-y)<=1e-7*pmax(1,abs(x),abs(y))
if (!close(back(as.numeric(fit$b)),p$pooled) || !close(back(fit$ci.lb),p$ci_lower) ||
    !close(back(fit$ci.ub),p$ci_upper)) stop("reconstructed model differs from bound pooled result",call.=FALSE)
infl <- stats::influence(fit)
v <- infl$inf
result <- data.frame(study_id=d$study_id,source_record_id=if("record_id" %in% names(d)) d$record_id else "",
  rstudent=v$rstudent,dffits=v$dffits,cook_distance=v$cook.d,covariance_ratio=v$cov.r,
  leverage=v$hat,weight_percent=v$weight,metafor_influence_flag=as.logical(infl$is.infl))
write.csv(result,file.path(target,"influence.csv"),row.names=FALSE,na="")
egger <- data.frame(status="NOT_RUN_LOW_K",reason="Fewer than 10 independent studies; asymmetry test would be low powered",
  k=nrow(d),predictor="standard_error",model=p$model,z=NA_real_,p_value=NA_real_,
  asymmetry_slope=NA_real_,limit_effect=NA_real_,limit_ci_lower=NA_real_,limit_ci_upper=NA_real_)
if(nrow(d)>=10) {
  test <- tryCatch(metafor::regtest(fit,model="rma",predictor="sei"),error=function(e)e)
  if(inherits(test,"error")) {
    egger$status <- "NOT_ESTIMABLE"
    egger$reason <- conditionMessage(test)
  } else if (!is.finite(as.numeric(test$zval)) || !is.finite(as.numeric(test$pval)) ||
             !is.finite(as.numeric(test$est))) {
    egger$status <- "NOT_ESTIMABLE"
    egger$reason <- "metafor returned non-finite asymmetry coefficients"
  } else {
    egger$status <- "EXPLORATORY_TEST_RESULT";egger$reason <- "Asymmetry is not proof of publication bias"
    egger$z <- as.numeric(test$zval);egger$p_value <- as.numeric(test$pval)
    egger$asymmetry_slope <- as.numeric(stats::coef(test$fit)[2])
    egger$limit_effect <- as.numeric(test$est);egger$limit_ci_lower <- as.numeric(test$ci.lb)
    egger$limit_ci_upper <- as.numeric(test$ci.ub)
  }
}
write.csv(egger,file.path(target,"small_study_test.csv"),row.names=FALSE,na="")
png(file.path(target,"funnel.png"),width=1800,height=1500,res=200)
metafor::funnel(fit,atransf=if(p$effect_type %in% c("RR","OR","HR")) exp else NULL,
  xlab=paste(p$effect_type,if(p$effect_type %in% c("RR","OR","HR")) "ratio" else "effect"),
  main=paste("Exploratory funnel; k=",nrow(d),";",if(nrow(d)<10) "asymmetry test not run" else egger$status))
dev.off()
cat("DONE",nrow(d),egger$status,"\n")
