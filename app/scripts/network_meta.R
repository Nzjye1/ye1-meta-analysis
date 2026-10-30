args <- commandArgs(trailingOnly=TRUE)
if (length(args)!=3) stop("Usage: network_meta.R CONTRASTS PLAN OUT",call.=FALSE)
script <- sub("^--file=","",grep("^--file=",commandArgs(FALSE),value=TRUE)[1])
if (!file.exists(script)) script <- gsub("~+~"," ",script,fixed=TRUE)
root <- normalizePath(file.path(dirname(script),".."),mustWork=TRUE)
.libPaths(c(file.path(root,"method-r-library"),file.path(root,"r-library"),.libPaths()))
if (!requireNamespace("netmeta",quietly=TRUE) || !requireNamespace("meta",quietly=TRUE)) stop("netmeta/meta missing from project-private library",call.=FALSE)
d <- read.csv(args[1],stringsAsFactors=FALSE,check.names=FALSE,fileEncoding="UTF-8-BOM")
p <- as.list(read.csv(args[2],stringsAsFactors=FALSE,check.names=FALSE,fileEncoding="UTF-8-BOM")[1,,drop=FALSE])
out <- normalizePath(args[3],mustWork=TRUE)
if (!all(c("study_id","cohort_id","treat1","treat2","TE","seTE") %in% names(d)) || nrow(d)<3 ||
    any(!is.finite(d$TE)) || any(!is.finite(d$seTE) | d$seTE<=0)) stop("invalid network contrast data",call.=FALSE)
if (!(p$effect_type %in% c("MD","OR","RR")) || !(p$model %in% c("FE","RE")) ||
    !(p$small_values %in% c("good","bad")) || !(p$reference_treatment %in% c(d$treat1,d$treat2))) stop("invalid network plan",call.=FALSE)
if (!(p$tau_method %in% if(p$model=="RE") c("REML","DL") else "NONE")) stop("invalid model/tau method",call.=FALSE)
fit <- netmeta::netmeta(TE=d$TE,seTE=d$seTE,treat1=d$treat1,treat2=d$treat2,studlab=d$study_id,
  sm=p$effect_type,reference.group=p$reference_treatment,common=p$model=="FE",random=p$model=="RE",
  method.tau=if(p$model=="RE") p$tau_method else "DL",level=1-p$alpha,level.ma=1-p$alpha,
  small.values=p$small_values,backtransf=FALSE)
if (p$model=="FE") {
  te <- fit$TE.common; se <- fit$seTE.common; lo <- fit$lower.common; hi <- fit$upper.common
} else {
  te <- fit$TE.random; se <- fit$seTE.random; lo <- fit$lower.random; hi <- fit$upper.random
}
if (!is.matrix(te) || any(!is.finite(te)) || any(!is.finite(se))) stop("network effects not estimable",call.=FALSE)
trts <- rownames(te); ref <- p$reference_treatment
if (is.null(trts) || !(ref %in% trts)) stop("network reference missing",call.=FALSE)
scale <- if (p$effect_type %in% c("OR","RR")) "log_ratio" else "mean_difference"
reference <- data.frame(treatment=trts[trts!=ref],reference=ref,
  estimate=te[trts!=ref,ref],se=se[trts!=ref,ref],ci_lower=lo[trts!=ref,ref],ci_upper=hi[trts!=ref,ref],
  scale=scale,stringsAsFactors=FALSE)
if (scale=="log_ratio") {
  reference$display_estimate <- exp(reference$estimate)
  reference$display_lower <- exp(reference$ci_lower)
  reference$display_upper <- exp(reference$ci_upper)
} else {
  reference$display_estimate <- reference$estimate
  reference$display_lower <- reference$ci_lower
  reference$display_upper <- reference$ci_upper
}
write.csv(reference,file.path(out,"reference_effects.csv"),row.names=FALSE)
league <- do.call(rbind,lapply(trts,function(a) do.call(rbind,lapply(trts,function(b) {
  if (a==b) return(NULL)
  data.frame(treat1=a,treat2=b,estimate=te[a,b],se=se[a,b],ci_lower=lo[a,b],ci_upper=hi[a,b],scale=scale)
}))))
write.csv(league,file.path(out,"league_table.csv"),row.names=FALSE)
rank <- netmeta::netrank(fit,small.values=p$small_values)
score <- if (p$model=="FE") rank$ranking.common else rank$ranking.random
if (is.null(score) || any(!is.finite(score))) stop("network P-scores unavailable",call.=FALSE)
write.csv(data.frame(treatment=names(score),p_score=as.numeric(score),direction=p$small_values,
  interpretation="model_based_P_score_not_benefit_probability"),file.path(out,"ranking.csv"),row.names=FALSE)
qinc <- fit$Q.inconsistency; dfinc <- fit$df.Q.inconsistency; pinc <- fit$pval.Q.inconsistency
status <- if (length(dfinc)!=1 || is.na(dfinc) || dfinc<=0) "NOT_ESTIMABLE_NO_INDEPENDENT_INCONSISTENCY_DF" else "ESTIMATED_REVIEW_REQUIRED"
summary <- data.frame(n_studies=length(unique(d$study_id)),n_contrasts=nrow(d),n_treatments=length(trts),
  reference=ref,effect_type=p$effect_type,scale=scale,model=p$model,tau_method=if(p$model=="RE") fit$method.tau else "NONE",
  tau2=if(p$model=="RE") fit$tau2 else 0,Q=fit$Q,Q_heterogeneity=fit$Q.heterogeneity,
  Q_inconsistency=if(length(qinc)==1 && is.finite(qinc)) qinc else NA_real_,
  df_inconsistency=if(length(dfinc)==1 && is.finite(dfinc)) dfinc else NA_real_,
  p_inconsistency=if(length(pinc)==1 && is.finite(pinc)) pinc else NA_real_,
  inconsistency_status=status,netmeta_version=as.character(utils::packageVersion("netmeta")))
write.csv(summary,file.path(out,"network_summary.csv"),row.names=FALSE,na="")
local <- data.frame(comparison=character(),direct_TE=numeric(),indirect_TE=numeric(),direct_indirect_p=numeric(),status=character())
if (status=="ESTIMATED_REVIEW_REQUIRED") {
  split <- netmeta::netsplit(fit)
  direct <- if(p$model=="FE") split$direct.common else split$direct.random
  indirect <- if(p$model=="FE") split$indirect.common else split$indirect.random
  compare <- if(p$model=="FE") split$compare.common else split$compare.random
  if (!identical(as.character(direct$comparison),as.character(indirect$comparison))) stop("netsplit comparison mismatch",call.=FALSE)
  local <- data.frame(comparison=direct$comparison,direct_TE=direct$TE,indirect_TE=indirect$TE,
    direct_indirect_p=compare$p,status=ifelse(is.finite(direct$TE) & is.finite(indirect$TE),"ESTIMABLE_REVIEW_REQUIRED","NO_DIRECT_OR_INDIRECT_PAIR"))
} else local <- data.frame(comparison="NETWORK",direct_TE=NA_real_,indirect_TE=NA_real_,direct_indirect_p=NA_real_,status=status)
write.csv(local,file.path(out,"local_inconsistency.csv"),row.names=FALSE,na="")
source(file.path(dirname(script),"network_figures.R"),local=TRUE)
network_figures(d,reference,p,out)
