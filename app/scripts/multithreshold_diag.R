args<-commandArgs(trailingOnly=TRUE)
if(length(args)!=3)stop("Usage: multithreshold_diag.R CUTOFFS PLAN OUT",call.=FALSE)
script<-sub("^--file=","",grep("^--file=",commandArgs(FALSE),value=TRUE)[1])
if(!file.exists(script))script<-gsub("~+~"," ",script,fixed=TRUE)
root<-normalizePath(file.path(dirname(script),".."),mustWork=TRUE)
.libPaths(c(file.path(root,"method-r-library"),file.path(root,"r-library"),.libPaths()))
if(!requireNamespace("diagmeta",quietly=TRUE))stop("diagmeta unavailable from project-private R library",call.=FALSE)
source(file.path(dirname(script),"diagmeta_fit_check.R"),local=TRUE)
d<-read.csv(args[1],stringsAsFactors=FALSE,check.names=FALSE,fileEncoding="UTF-8-BOM")
p<-as.list(read.csv(args[2],stringsAsFactors=FALSE,check.names=FALSE,fileEncoding="UTF-8-BOM")[1,,drop=FALSE])
out<-normalizePath(args[3],mustWork=TRUE)
if(nrow(d)<3||p$model!="CICS"||p$distribution!="logistic"||p$method_weights!="invvar"||p$positive_direction!="higher_value_positive")
  stop("invalid checked multithreshold plan",call.=FALSE)
alpha<-as.numeric(p$alpha);lambda<-as.numeric(p$lambda_sensitivity);incr<-as.numeric(p$continuity_increment)
grid<-as.numeric(strsplit(as.character(p$prediction_cutoffs),"|",fixed=TRUE)[[1]])
logged<-tolower(as.character(p$log_cutoff))=="true"
if(!is.finite(alpha)||alpha<=0||alpha>=.5||!is.finite(lambda)||lambda<0||lambda>1||incr!=.5||any(!is.finite(grid)))
  stop("invalid alpha/lambda/continuity/grid",call.=FALSE)
if(any(!is.finite(d$threshold))||any(!is.finite(as.matrix(d[,c("TP","FN","FP","TN")])))||any(d$TP+d$FN<=0)||any(d$FP+d$TN<=0))
  stop("invalid checked cutoff counts",call.=FALSE)
fit<-diagmeta::diagmeta(TP=d$TP,FP=d$FP,TN=d$TN,FN=d$FN,cutoff=d$threshold,studlab=d$study_id,
                        distr="logistic",model="CICS",equalvar=FALSE,lambda=lambda,log.cutoff=logged,
                        method.weights="invvar",level=1-alpha,incr=.5,silent=TRUE)
fit_check<-check_diagmeta_lmer(fit$result.lmer)
stats<-diagmeta::diagstats(fit,cutoff=grid,level=1-alpha)
required<-c("cutoff","Sens","Spec","lower.Sens","upper.Sens","lower.Spec","upper.Spec")
if(!all(required %in% names(stats))||nrow(stats)!=length(grid)||any(!is.finite(as.matrix(stats[,required]))))
  stop("diagmeta cutoff predictions incomplete/nonfinite",call.=FALSE)
pred<-stats[,required,drop=FALSE]
names(pred)<-c("cutoff","sensitivity","specificity","sensitivity_lower","sensitivity_upper","specificity_lower","specificity_upper")
pred$threshold_unit<-p$threshold_unit
pred$model_fit_status<-fit_check$status
write.csv(pred,file.path(out,"cutoff_predictions.csv"),row.names=FALSE)
warn<-as.character(p$inconsistent_total_studies)
if(is.na(warn))warn<-""
result<-data.frame(n_studies=length(unique(d$study_id)),n_cutoff_rows=nrow(d),
                   n_multicutoff_studies=sum(table(d$study_id)>1),model="diagmeta CICS logistic unequal-variance",
                   weighting="inverse-variance",log_cutoff=logged,lambda_sensitivity=lambda,continuity_increment=incr,
                   alpha=alpha,threshold_unit=p$threshold_unit,optimal_cutoff=as.numeric(fit$optcut),
                   sensitivity_optimal=as.numeric(fit$Sens.optcut),sensitivity_lower=as.numeric(fit$lower.Sens.optcut),
                   sensitivity_upper=as.numeric(fit$upper.Sens.optcut),specificity_optimal=as.numeric(fit$Spec.optcut),
                   specificity_lower=as.numeric(fit$lower.Spec.optcut),specificity_upper=as.numeric(fit$upper.Spec.optcut),
                   AUC_sensitivity=as.numeric(fit$AUCSens),AUC_specificity=as.numeric(fit$AUCSpec),
                   package_example_inconsistent_total_studies=warn,
                   fit_status=fit_check$status,optimizer_code=fit_check$optimizer_code,
                   singular_boundary=fit_check$singular_boundary,optimizer_messages=fit_check$optimizer_messages,
                   diagmeta_version=as.character(utils::packageVersion("diagmeta")))
if(any(!is.finite(as.matrix(result[,c("optimal_cutoff","sensitivity_optimal","specificity_optimal"),drop=FALSE]))))stop("diagmeta optimal summary nonfinite",call.=FALSE)
write.csv(result,file.path(out,"multithreshold_summary.csv"),row.names=FALSE,na="")
trace<-data.frame(study_id=d$study_id,cohort_id=d$cohort_id,threshold=d$threshold,threshold_unit=d$threshold_unit,
                  TP=d$TP,FN=d$FN,FP=d$FP,TN=d$TN,diseased_total=d$TP+d$FN,nondiseased_total=d$FP+d$TN,
                  raw_sensitivity=d$TP/(d$TP+d$FN),raw_specificity=d$TN/(d$FP+d$TN),
                  source_file=d$source_file,source_sha256=d$source_sha256,source_location=d$source_location)
write.csv(trace,file.path(out,"cutoff_trace.csv"),row.names=FALSE)
report<-c("# Several-cutoff diagnostic meta-analysis: statistical facts","",
          paste("Source:",p$source_kind,"; labeled study groups:",result$n_studies,"; cutoff rows:",nrow(d),"; groups with multiple cutoffs:",result$n_multicutoff_studies),
          paste("Index test:",p$index_test,"; reference standard:",p$reference_standard,"; condition:",p$outcome,"at",p$timepoint),
          paste("Model: CICS logistic, unequal variances, inverse-variance study weights; log cutoff:",logged,"; lambda sensitivity:",lambda,"; continuity increment:",incr),
          paste("Model-derived optimal cutoff:",format(result$optimal_cutoff,digits=8),p$threshold_unit,"; sensitivity:",format(result$sensitivity_optimal,digits=8),"; specificity:",format(result$specificity_optimal,digits=8)),
          paste("Underlying lme4 optimizer code:",fit_check$optimizer_code,"; model-fit status:",fit_check$status,
                if(fit_check$singular_boundary)"; boundary (singular) fit: uncertainty and model assumptions need special review" else ""),
          if(nzchar(warn))paste("PACKAGE DATA WARNING: disease-group totals change across cutoffs in labeled group(s):",warn,". The package method example is retained without silently altering source rows. Real/synthetic analyses would be blocked.") else "Within each labeled study, disease-group totals and monotonic cutoffs passed the explicit consistency check.",
          "Cutoffs from a study are correlated observations, not independent studies. Model-selected cutoffs require external clinical validation and do not establish a clinical decision threshold.",
          "Source hashes check local bytes only; subgroup cohort independence and source extraction are not authenticated. This is a non-final methods result, not a completed diagnostic review.")
writeLines(report,file.path(out,"fact_report.md"),useBytes=TRUE)
png(file.path(out,"sensspec_curve.png"),width=1100,height=850,res=130)
par(mar=c(7,4,4,2)+.1)
plot(fit,which="sensspec",xlab=paste0("Cutoff (",p$threshold_unit,")"),main=TRUE,ci=TRUE,mark.optcut=TRUE)
if(p$source_kind!="reviewed_extraction")mtext(if(p$source_kind=="synthetic_fixture")"SYNTHETIC DATA" else "PACKAGE METHOD EXAMPLE",side=3,line=.2,cex=.65)
if(fit_check$singular_boundary)mtext("BOUNDARY (SINGULAR) FIT - interpret with caution",side=1,line=5.1,cex=.62,col="darkred")
dev.off()
png(file.path(out,"sroc.png"),width=1100,height=850,res=130)
par(mar=c(7,4,4,2)+.1)
plot(fit,which="sroc",main=TRUE,mark.optcut=TRUE)
if(p$source_kind!="reviewed_extraction")mtext(if(p$source_kind=="synthetic_fixture")"SYNTHETIC DATA" else "PACKAGE METHOD EXAMPLE",side=3,line=.2,cex=.65)
if(fit_check$singular_boundary)mtext("BOUNDARY (SINGULAR) FIT - interpret with caution",side=1,line=5.1,cex=.62,col="darkred")
dev.off()
