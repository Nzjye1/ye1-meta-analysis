args <- commandArgs(trailingOnly=TRUE)
if (length(args)!=5) stop("Usage: diagnostic_meta.R INPUT ZERO_POLICY ALPHA THRESHOLD_POLICY OUT",call.=FALSE)
script <- sub("^--file=","",grep("^--file=",commandArgs(FALSE),value=TRUE)[1])
if (!file.exists(script)) script <- gsub("~+~"," ",script,fixed=TRUE)
root <- normalizePath(file.path(dirname(script),".."),mustWork=TRUE)
.libPaths(c(file.path(root,"method-r-library"),file.path(root,"r-library"),.libPaths()))
if (!requireNamespace("mada",quietly=TRUE)) stop("mada missing from project-private R library",call.=FALSE)
d <- read.csv(args[1],stringsAsFactors=FALSE,check.names=FALSE,fileEncoding="UTF-8-BOM")
if (!all(c("study_id","TP","FN","FP","TN") %in% names(d)) || nrow(d)<3 || anyDuplicated(d$study_id)) stop("invalid checked 2x2 table",call.=FALSE)
cells <- as.matrix(d[,c("TP","FN","FP","TN")])
if (any(!is.finite(cells) | cells<0 | cells!=floor(cells)) || any(d$TP+d$FN==0) || any(d$FP+d$TN==0)) stop("invalid 2x2 counts",call.=FALSE)
if (!(args[2] %in% c("reject","half_all","half_single"))) stop("invalid zero policy",call.=FALSE)
alpha <- as.numeric(args[3]); if (!is.finite(alpha) || alpha<=0 || alpha>=0.5) stop("invalid alpha",call.=FALSE)
if (args[2]=="reject" && any(cells==0)) stop("zero cell under reject policy",call.=FALSE)
correction <- if (args[2]=="reject") 0 else 0.5
control <- if (args[2]=="half_single") "single" else "all"
if (!(args[4] %in% c("common","mixed_exploratory"))) stop("invalid threshold policy",call.=FALSE)
out <- normalizePath(args[5],mustWork=TRUE)
basic <- d[,c("TP","FN","FP","TN")]
rownames(basic) <- d$study_id
fit <- mada::reitsma(basic,correction=correction,correction.control=control,method="reml")
s <- summary(fit,level=1-alpha)
if (!isTRUE(s$converged)) stop("mada bivariate fit did not converge",call.=FALSE)
co <- s$coefficients
sens <- co["sensitivity",]
fpr <- co["false pos. rate",]
lower <- grep("%ci\\.lb$",colnames(co),value=TRUE)
upper <- grep("%ci\\.ub$",colnames(co),value=TRUE)
if (length(lower)!=1 || length(upper)!=1) stop("mada summary confidence columns missing",call.=FALSE)
scope <- if (length(unique(d$threshold))>1) "MIXED_THRESHOLDS_EXPLORATORY" else "COMMON_THRESHOLD_LABEL_UNVERIFIED_CLINICALLY"
scope_label <- if (scope=="MIXED_THRESHOLDS_EXPLORATORY") "Mixed thresholds: exploratory" else "Common threshold label: equivalence unverified"
if (scope=="MIXED_THRESHOLDS_EXPLORATORY" && args[4]!="mixed_exploratory") stop("mixed threshold plan mismatch",call.=FALSE)
result <- data.frame(k=nrow(d),model="Reitsma bivariate REML",zero_policy=args[2],threshold_policy=args[4],interpretation_scope=scope,alpha=alpha,
  sensitivity=sens["Estimate"],sensitivity_lower=sens[lower],sensitivity_upper=sens[upper],
  specificity=1-fpr["Estimate"],specificity_lower=1-fpr[upper],specificity_upper=1-fpr[lower],
  false_positive_rate=fpr["Estimate"],converged=TRUE,mada_version=as.character(utils::packageVersion("mada")))
write.csv(result,file.path(out,"diagnostic_summary.csv"),row.names=FALSE,na="")
has_zero <- rowSums(cells==0)>0
corrected <- if (args[2]=="reject") rep(FALSE,nrow(d)) else if (args[2]=="half_all") rep(any(has_zero),nrow(d)) else has_zero
trace <- data.frame(study_id=d$study_id,cohort_id=d$cohort_id,TP=d$TP,FN=d$FN,FP=d$FP,TN=d$TN,
  raw_sensitivity=d$TP/(d$TP+d$FN),raw_specificity=d$TN/(d$FP+d$TN),
  model_correction_applied=corrected,model_zero_policy=args[2],threshold=d$threshold,
  source_file=d$source_file,source_sha256=d$source_sha256,source_location=d$source_location)
write.csv(trace,file.path(out,"study_2x2_trace.csv"),row.names=FALSE)
png(file.path(out,"sroc.png"),width=1000,height=800,res=130)
par(mar=c(7,4,4,2))
plot(fit,main=if(scope=="MIXED_THRESHOLDS_EXPLORATORY") "Summary ROC: mixed thresholds, exploratory" else "Summary ROC: common threshold label")
mtext(paste("Zero-cell policy:",args[2],";",scope_label),side=1,line=5,cex=.65)
dev.off()
png(file.path(out,"paired_forest.png"),width=1600,height=1000,res=130)
par(mfrow=c(1,2),mar=c(4,6,3,1),oma=c(2,0,0,0))
per <- mada::madad(basic,correction=correction,correction.control=control)
mada::forest(per,type="sens",main="Sensitivity (model inputs)",xlab="Sensitivity",snames=d$study_id)
mada::forest(per,type="spec",main="Specificity (model inputs)",xlab="Specificity",snames=d$study_id)
mtext(paste("Model forest uses",args[2],"zero-cell rule; raw ratios are in study_2x2_trace.csv.",scope_label),side=1,outer=TRUE,line=0,cex=.7)
dev.off()
