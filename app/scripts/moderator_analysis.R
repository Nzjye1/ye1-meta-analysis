args <- commandArgs(trailingOnly=TRUE)
if (length(args)!=5) stop("Usage: Rscript moderator_analysis.R STATS_DIR MODERATORS_CSV PLAN_CSV MODE OUT_DIR",call.=FALSE)
script <- sub("^--file=","",grep("^--file=",commandArgs(FALSE),value=TRUE)[1])
if (!file.exists(script)) script <- gsub("~+~"," ",script,fixed=TRUE)
root <- normalizePath(file.path(dirname(script),".."),mustWork=TRUE)
source(file.path(root,"scripts","runtime_library.R"))
configure_meta_library(root)
if (!requireNamespace("metafor",quietly=TRUE)) stop("metafor missing from native R library",call.=FALSE)
folder <- normalizePath(args[1],mustWork=TRUE)
out <- normalizePath(args[5],mustWork=TRUE)
read_table <- function(path) read.csv(path,stringsAsFactors=FALSE,check.names=FALSE,fileEncoding="UTF-8-BOM")
d <- read_table(file.path(folder,"study_effects_trace.csv"))
p <- read_table(file.path(folder,"pooled_result.csv"))
m <- read_table(args[2])
spec <- read_table(args[3])
if (nrow(p)!=1 || !all(c("study_id","analysis_effect","analysis_variance","effect_type") %in% names(d)) ||
    !all(c("name","type","reference") %in% names(spec)) || !all(c("study_id","source_file","source_sha256","source_location") %in% names(m)))
  stop("invalid moderator input or base result schema",call.=FALSE)
if (!identical(sort(d$study_id),sort(m$study_id)) || anyDuplicated(d$study_id) || anyDuplicated(m$study_id) ||
    anyDuplicated(d$cohort_id) || any(!is.finite(d$analysis_effect)) ||
    any(!is.finite(d$analysis_variance) | d$analysis_variance<=0))
  stop("moderators must map one to one to independent study effects",call.=FALSE)
m <- m[match(d$study_id,m$study_id),,drop=FALSE]
if (any(d$effect_type!=p$effect_type) || !(p$model %in% c("FE","RE")) ||
    !((p$model=="FE" && p$tau_method=="NONE") || (p$model=="RE" && p$tau_method=="REML")) ||
    p$test!="z" || !is.finite(p$alpha) || p$alpha<=0 || p$alpha>=0.5)
  stop("base effect scale or statistical configuration invalid",call.=FALSE)
if (!(args[4] %in% c("subgroup","meta_regression")) ||
    (args[4]=="subgroup" && (nrow(spec)!=1 || spec$type!="categorical")))
  stop("invalid moderator mode",call.=FALSE)
md <- m
for (j in seq_len(nrow(spec))) {
  name <- spec$name[j]
  if (!(name %in% names(md)) || any(is.na(md[[name]]) | !nzchar(trimws(md[[name]]))))
    stop(paste("missing moderator",name),call.=FALSE)
  if (spec$type[j]=="continuous") {
    md[[name]] <- suppressWarnings(as.numeric(md[[name]]))
    if (any(!is.finite(md[[name]])) || length(unique(md[[name]]))<2)
      stop(paste("continuous moderator requires finite varying values:",name),call.=FALSE)
  } else if (spec$type[j]=="categorical") {
    levels <- sort(unique(md[[name]]))
    if (length(levels)<2 || !(spec$reference[j] %in% levels))
      stop(paste("categorical moderator needs at least two levels and observed reference:",name),call.=FALSE)
    md[[name]] <- factor(md[[name]],levels=c(spec$reference[j],setdiff(levels,spec$reference[j])))
  } else stop("invalid moderator type",call.=FALSE)
}
formula <- stats::reformulate(spec$name)
X <- stats::model.matrix(formula,data=md)
k <- nrow(d); param <- ncol(X)
if (qr(X)$rank!=param || k<=param)
  stop(paste("moderator design rank deficient or no residual degrees of freedom: k=",k,", p=",param),call.=FALSE)
fit <- metafor::rma.uni(yi=d$analysis_effect,vi=d$analysis_variance,mods=formula,
    data=md,method=if(p$model=="FE") "FE" else "REML",test="z",level=100*(1-p$alpha))
coeff <- data.frame(term=rownames(fit$beta),estimate=as.numeric(fit$beta),
    se=as.numeric(fit$se),ci_lower=as.numeric(fit$ci.lb),ci_upper=as.numeric(fit$ci.ub),
    z=as.numeric(fit$zval),p_value=as.numeric(fit$pval),
    scale=if(p$effect_type %in% c("RR","OR","HR")) "log_ratio" else "linear_effect")
write.csv(coeff,file.path(out,"moderator_coefficients.csv"),row.names=FALSE)
warning <- character()
if (k-param<4) warning <- c(warning,"few residual degrees of freedom; interpret associations cautiously")
if (k<10) warning <- c(warning,"fewer than 10 studies; low power and unstable between-study estimates")
if (any(vapply(spec$name,function(name) is.factor(md[[name]]) && any(table(md[[name]])==1),logical(1))))
  warning <- c(warning,"at least one categorical level contains one study; no pooled subgroup estimate for that level")
model <- data.frame(mode=args[4],effect_type=p$effect_type,model=p$model,tau_method=p$tau_method,
    alpha=p$alpha,k=k,p=param,residual_df=k-param,QM=as.numeric(fit$QM),
    QM_df=param-1,QM_p=as.numeric(fit$QMp),QE=as.numeric(fit$QE),
    QE_p=as.numeric(fit$QEp),tau2=as.numeric(fit$tau2),I2_percent=as.numeric(fit$I2),
    warning=paste(warning,collapse="; "))
write.csv(model,file.path(out,"moderator_model.csv"),row.names=FALSE)
write.csv(data.frame(d,m[setdiff(names(m),"study_id")]),file.path(out,"moderator_trace.csv"),row.names=FALSE)
back <- if (p$effect_type %in% c("RR","OR","HR")) exp else identity
if (args[4]=="subgroup") {
  name <- spec$name[1]
  groups <- levels(md[[name]])
  group_rows <- lapply(groups,function(g) {
    ids <- which(md[[name]]==g)
    if (length(ids)==1) {
      ci <- c(d$ci_lower[ids],d$ci_upper[ids])
      data.frame(level=g,k=1,status="SINGLE_STUDY_DESCRIPTIVE_NOT_POOLED",
                 pooled=d$estimate[ids],ci_lower=ci[1],ci_upper=ci[2],tau2=NA_real_)
    } else {
      sub <- metafor::rma.uni(yi=d$analysis_effect[ids],vi=d$analysis_variance[ids],
          method=if(p$model=="FE") "FE" else "REML",test="z",level=100*(1-p$alpha))
      data.frame(level=g,k=length(ids),status="POOLED_WITHIN_GROUP",
          pooled=back(as.numeric(sub$b)),ci_lower=back(sub$ci.lb),ci_upper=back(sub$ci.ub),tau2=sub$tau2)
    }
  })
  groups_out <- do.call(rbind,group_rows)
  write.csv(groups_out,file.path(out,"subgroup_results.csv"),row.names=FALSE)
  png(file.path(out,"subgroup_forest.png"),width=1200,height=max(700,250+100*nrow(groups_out)),res=140)
  tryCatch({
    y <- rev(seq_len(nrow(groups_out)))
    range <- range(c(groups_out$ci_lower,groups_out$ci_upper),finite=TRUE)
    plot(groups_out$pooled,y,xlim=range+diff(range)*c(-.08,.08),ylim=c(.5,nrow(groups_out)+.5),
         yaxt="n",ylab="",xlab=paste(p$effect_type,"effect scale"),pch=19,main="Subgroup estimates")
    axis(2,at=y,labels=paste(groups_out$level,"(k=",groups_out$k,")"),las=1)
    segments(groups_out$ci_lower,y,groups_out$ci_upper,y,lwd=2)
    abline(v=if(p$effect_type %in% c("RR","OR","HR")) 1 else 0,lty=2,col="gray40")
  },finally=dev.off())
}
png(file.path(out,"coefficient_plot.png"),width=1200,height=max(700,250+100*nrow(coeff)),res=140)
tryCatch({
  y <- rev(seq_len(nrow(coeff)))
  range <- range(c(coeff$ci_lower,coeff$ci_upper),finite=TRUE)
  if (diff(range)==0) range <- range+c(-1,1)
  plot(coeff$estimate,y,xlim=range+diff(range)*c(-.08,.08),ylim=c(.5,nrow(coeff)+.5),
       yaxt="n",ylab="",xlab=if(p$effect_type %in% c("RR","OR","HR")) "log effect ratio" else p$effect_type,
       pch=19,main="Moderator model coefficients")
  axis(2,at=y,labels=coeff$term,las=1)
  segments(coeff$ci_lower,y,coeff$ci_upper,y,lwd=2)
  abline(v=0,lty=2,col="gray40")
},finally=dev.off())
if (args[4]=="meta_regression" && nrow(spec)==1 && spec$type[1]=="continuous") {
  name <- spec$name[1]
  values <- seq(min(md[[name]]),max(md[[name]]),length.out=100)
  predicted <- predict(fit,newmods=values,level=100*(1-p$alpha))
  png(file.path(out,"moderator_scatter.png"),width=1200,height=800,res=140)
  tryCatch({
    plot(md[[name]],d$analysis_effect,pch=19,xlab=name,
         ylab=if(p$effect_type %in% c("RR","OR","HR")) "log effect ratio" else p$effect_type,
         main="Observed study effects and meta-regression fit")
    lines(values,predicted$pred,lwd=2,col="blue")
    lines(values,predicted$ci.lb,lty=2,col="blue")
    lines(values,predicted$ci.ub,lty=2,col="blue")
  },finally=dev.off())
}
