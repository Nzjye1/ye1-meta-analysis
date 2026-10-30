args <- commandArgs(trailingOnly=TRUE)
if (length(args)!=2) stop("Usage: Rscript prediction_interval.R BOUND_STATS_DIR OUTPUT_CSV",call.=FALSE)
folder <- normalizePath(args[1],mustWork=TRUE)
target <- args[2]
script <- sub("^--file=","",grep("^--file=",commandArgs(FALSE),value=TRUE)[1])
if (!file.exists(script)) script <- gsub("~+~"," ",script,fixed=TRUE)
root <- normalizePath(file.path(dirname(script),".."),mustWork=TRUE)
source(file.path(root,"scripts","runtime_library.R"))
configure_meta_library(root)
if (!requireNamespace("metafor",quietly=TRUE)) stop("metafor missing from native R library",call.=FALSE)
d <- read.csv(file.path(folder,"study_effects_trace.csv"),check.names=FALSE,fileEncoding="UTF-8-BOM")
p <- read.csv(file.path(folder,"pooled_result.csv"),check.names=FALSE,fileEncoding="UTF-8-BOM")
need <- c("study_id","analysis_effect","analysis_variance")
if (!all(need %in% names(d)) || nrow(p)!=1 || !all(c("model","tau_method","test","alpha","effect_type","k","pooled","ci_lower","ci_upper","tau2") %in% names(p)))
  stop("bound statistics schema invalid",call.=FALSE)
if (p$model!="RE" || p$tau_method!="REML" || p$test!="z" || nrow(d)<3 || p$k!=nrow(d))
  stop("prediction interval requires at least three independent studies and RE/REML/z",call.=FALSE)
if (!is.finite(p$alpha) || p$alpha<=0 || p$alpha>=0.5 || any(!is.finite(d$analysis_effect)) ||
    any(!is.finite(d$analysis_variance) | d$analysis_variance<=0) || anyDuplicated(d$study_id))
  stop("invalid effect variance, alpha, or repeated study ID",call.=FALSE)
if (!(p$effect_type %in% c("RR","OR","HR","MD","SMD"))) stop("unsupported effect type",call.=FALSE)
fit <- metafor::rma.uni(yi=d$analysis_effect,vi=d$analysis_variance,method="REML",test="z",
                        level=100*(1-p$alpha),slab=d$study_id)
back <- if (p$effect_type %in% c("RR","OR","HR")) exp else identity
pred <- predict(fit,level=100*(1-p$alpha))
close <- function(x,y) is.finite(x) && is.finite(y) && abs(x-y)<=1e-7*pmax(1,abs(x),abs(y))
if (!close(back(as.numeric(fit$b)),p$pooled) || !close(back(fit$ci.lb),p$ci_lower) ||
    !close(back(fit$ci.ub),p$ci_upper) || !close(fit$tau2,p$tau2))
  stop("reconstructed model disagrees with bound pooled statistics",call.=FALSE)
if (!is.finite(pred$pi.lb) || !is.finite(pred$pi.ub) || pred$pi.lb>=pred$pi.ub)
  stop("metafor did not return a finite prediction interval",call.=FALSE)
result <- data.frame(effect_type=p$effect_type,model="RE",tau_method="REML",test="z",alpha=p$alpha,
  k=fit$k,pooled=back(as.numeric(pred$pred)),ci_lower=back(as.numeric(pred$ci.lb)),
  ci_upper=back(as.numeric(pred$ci.ub)),pi_lower=back(as.numeric(pred$pi.lb)),
  pi_upper=back(as.numeric(pred$pi.ub)),tau2=fit$tau2,
  prediction_method="metafor::predict.rma; normal critical value; estimated tau2",
  ratio_interpretation=if(p$effect_type %in% c("RR","OR","HR")) "median ratio on back-transformed scale" else "linear effect scale")
write.csv(result,target,row.names=FALSE)
