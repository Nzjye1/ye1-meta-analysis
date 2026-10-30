args <- commandArgs(trailingOnly=TRUE)
if (length(args)!=3) stop("Usage: dose_response.R CATEGORIES ENGINE_PLAN OUT",call.=FALSE)
script <- sub("^--file=","",grep("^--file=",commandArgs(FALSE),value=TRUE)[1])
if (!file.exists(script)) script <- gsub("~+~"," ",script,fixed=TRUE)
root <- normalizePath(file.path(dirname(script),".."),mustWork=TRUE)
.libPaths(c(file.path(root,"method-r-library"),file.path(root,"r-library"),.libPaths()))
if (!requireNamespace("dosresmeta",quietly=TRUE)) stop("dosresmeta missing from project-private R library",call.=FALSE)
d <- read.csv(args[1],stringsAsFactors=FALSE,check.names=FALSE,fileEncoding="UTF-8-BOM")
p <- as.list(read.csv(args[2],stringsAsFactors=FALSE,check.names=FALSE,fileEncoding="UTF-8-BOM")[1,,drop=FALSE])
out <- normalizePath(args[3],mustWork=TRUE)
if (!all(c("study_id","dose","logrr","se","cases","n","type","reference") %in% names(d)) ||
    nrow(d)<9 || !(p$model %in% c("linear","natural_spline")) || p$covariance!="greenland_longnecker" || p$method!="REML")
  stop("invalid checked dose input or model plan",call.=FALSE)
if (any(!is.finite(d$dose) | !is.finite(d$logrr) | !is.finite(d$cases) | !is.finite(d$n)) ||
    any(d$reference=="NO" & (!is.finite(d$se) | d$se<=0))) stop("invalid checked dose values",call.=FALSE)
alpha <- as.numeric(p$alpha); ref <- as.numeric(p$reference_dose)
grid <- as.numeric(strsplit(as.character(p$prediction_doses),"|",fixed=TRUE)[[1]])
if (!is.finite(alpha) || alpha<=0 || alpha>=.5 || !is.finite(ref) || any(!is.finite(grid))) stop("invalid alpha, reference or dose grid",call.=FALSE)
if (p$model=="linear") {
  formula <- stats::as.formula("logrr ~ dose")
} else {
  knots <- as.numeric(strsplit(as.character(p$knots),"|",fixed=TRUE)[[1]])
  bounds <- as.numeric(strsplit(as.character(p$boundary_knots),"|",fixed=TRUE)[[1]])
  if (any(!is.finite(knots)) || length(bounds)!=2 || any(!is.finite(bounds))) stop("invalid spline knots",call.=FALSE)
  expr <- paste0("logrr ~ splines::ns(dose, knots=c(",paste(knots,collapse=","),"), Boundary.knots=c(",paste(bounds,collapse=","),"))")
  formula <- stats::as.formula(expr)
}
fit <- dosresmeta::dosresmeta(formula,id=d$study_id,type=d$type,cases=d$cases,n=d$n,se=d$se,
                              data=d,covariance="gl",method="reml",proc="2stage")
summary <- summary(fit,ci.level=1-alpha)
if (!isTRUE(fit$converged)) stop("dosresmeta did not converge",call.=FALSE)
co <- summary$coefficients
lower <- grep("%ci\\.lb$",colnames(co),value=TRUE); upper <- grep("%ci\\.ub$",colnames(co),value=TRUE)
if (length(lower)!=1 || length(upper)!=1) stop("coefficient confidence interval columns missing",call.=FALSE)
terms <- if (p$model=="linear") "dose_per_unit_logRR" else rownames(co)
coef_data <- data.frame(term=terms,estimate=co[,"Estimate"],se=co[,"Std. Error"],
                        ci_lower=co[,lower],ci_upper=co[,upper],p_value=co[,"Pr(>|z|)"],scale="log_RR")
write.csv(coef_data,file.path(out,"dose_coefficients.csv"),row.names=FALSE)
prediction <- stats::predict(fit,newdata=data.frame(dose=grid),xref=ref,expo=TRUE,ci.level=1-alpha)
if (any(!is.finite(prediction$pred)) || any(!is.finite(prediction$ci.lb)) || any(!is.finite(prediction$ci.ub))) stop("nonfinite dose prediction",call.=FALSE)
pred_data <- data.frame(dose=grid,reference_dose=ref,RR=prediction$pred,ci_lower=prediction$ci.lb,ci_upper=prediction$ci.ub,
                        dose_unit=p$dose_unit,model=p$model)
write.csv(pred_data,file.path(out,"dose_predictions.csv"),row.names=FALSE)
ids <- unique(d$study_id)
if (length(fit$Slist)!=length(ids)) stop("within-study covariance list count mismatch",call.=FALSE)
cov_rows <- list()
for (j in seq_along(ids)) {
  nonref <- d[d$study_id==ids[j] & d$reference=="NO",,drop=FALSE]
  S <- fit$Slist[[j]]
  if (!is.matrix(S) || nrow(S)!=nrow(nonref) || ncol(S)!=nrow(nonref) || any(!is.finite(S)) ||
      max(abs(S-t(S)))>1e-8) stop("within-study GL covariance could not be aligned with dose rows",call.=FALSE)
  cov_rows[[j]] <- data.frame(study_id=ids[j],row_index=rep(seq_len(nrow(S)),each=ncol(S)),
    column_index=rep(seq_len(ncol(S)),times=nrow(S)),
    row_dose=rep(nonref$dose,each=ncol(S)),column_dose=rep(nonref$dose,times=nrow(S)),
    covariance=as.vector(t(S)),method="Greenland-Longnecker from supplied cases/denominators")
}
write.csv(do.call(rbind,cov_rows),file.path(out,"within_study_covariance.csv"),row.names=FALSE)
P <- fit$Psi
between <- data.frame(row_index=rep(seq_len(nrow(P)),each=ncol(P)),column_index=rep(seq_len(ncol(P)),times=nrow(P)),
                      covariance=as.vector(t(P)),model="REML_between_study")
write.csv(between,file.path(out,"between_study_covariance.csv"),row.names=FALSE)
q <- summary$qstat
result <- data.frame(n_studies=length(ids),n_categories=nrow(d),model=p$model,covariance="Greenland-Longnecker",
                     method="two-stage REML",reference_dose=ref,dose_unit=p$dose_unit,alpha=alpha,
                     Q=as.numeric(q$Q[1]),Q_df=as.numeric(q$df[1]),Q_p=as.numeric(q$pvalue[1]),
                     converged=TRUE,dosresmeta_version=as.character(utils::packageVersion("dosresmeta")))
write.csv(result,file.path(out,"dose_summary.csv"),row.names=FALSE)
write.csv(d,file.path(out,"category_trace.csv"),row.names=FALSE,na="")
ord <- order(pred_data$dose)
png(file.path(out,"dose_curve.png"),width=1100,height=850,res=130)
par(mar=c(5,5,4,2))
plot(pred_data$dose[ord],pred_data$RR[ord],type="n",ylim=range(c(pred_data$ci_lower,pred_data$ci_upper)),
     xlab=paste0("Dose (",p$dose_unit,")"),ylab="Relative risk versus reference",main=paste("Dose-response:",gsub("_"," ",p$model)))
polygon(c(pred_data$dose[ord],rev(pred_data$dose[ord])),c(pred_data$ci_lower[ord],rev(pred_data$ci_upper[ord])),
        col=grDevices::adjustcolor("lightblue",alpha.f=.5),border=NA)
lines(pred_data$dose[ord],pred_data$RR[ord],lwd=2)
abline(h=1,lty=2,col="gray40")
abline(v=ref,lty=3,col="gray40")
rug(d$dose,col="gray60")
if (p$source_kind!="reviewed_extraction") mtext(if (p$source_kind=="synthetic_fixture") "SYNTHETIC DATA" else "PACKAGE METHOD EXAMPLE",side=3,line=.2,cex=.65)
dev.off()
