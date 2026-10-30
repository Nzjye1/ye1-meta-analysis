args<-commandArgs(trailingOnly=TRUE)
if(length(args)!=3)stop("Usage: single_arm.R STUDIES PLAN OUT",call.=FALSE)
script<-sub("^--file=","",grep("^--file=",commandArgs(FALSE),value=TRUE)[1])
if(!file.exists(script))script<-gsub("~+~"," ",script,fixed=TRUE)
root<-normalizePath(file.path(dirname(script),".."),mustWork=TRUE)
.libPaths(c(file.path(root,"method-r-library"),file.path(root,"r-library"),.libPaths()))
if(!requireNamespace("metafor",quietly=TRUE))stop("metafor unavailable",call.=FALSE)
d<-read.csv(args[1],stringsAsFactors=FALSE,check.names=FALSE,fileEncoding="UTF-8-BOM")
p<-as.list(read.csv(args[2],stringsAsFactors=FALSE,check.names=FALSE,fileEncoding="UTF-8-BOM")[1,,drop=FALSE])
out<-normalizePath(args[3],mustWork=TRUE)
if(nrow(d)<3 || !(p$measure %in% c("proportion","incidence_rate")) || !(p$model %in% c("FE","REML")))
  stop("invalid checked single-group input/plan",call.=FALSE)
alpha<-as.numeric(p$alpha);scale<-as.numeric(p$display_per)
if(!is.finite(alpha)||alpha<=0||alpha>=.5||!is.finite(scale)||scale<=0)stop("invalid alpha/scale",call.=FALSE)
if(p$measure=="proportion") {
  if(p$denominator_unit!="people"||scale!=1||any(d$events<=0|d$events>=d$denominator))stop("proportion denominator invalid",call.=FALSE)
  es<-metafor::escalc(measure="PLO",xi=d$events,ni=d$denominator,add=0,to="none")
  inverse<-stats::plogis
  display_unit<-"proportion (fraction of people)"
} else {
  if(!(p$denominator_unit %in% c("person_years","person_months","person_days"))||any(d$events<=0|d$denominator<=0))stop("rate denominator invalid",call.=FALSE)
  es<-metafor::escalc(measure="IRLN",xi=d$events,ti=d$denominator,add=0,to="none")
  inverse<-function(x)exp(x)*scale
  display_unit<-paste0("events per ",scale," ",p$denominator_unit)
}
if(any(!is.finite(es$yi)|!is.finite(es$vi)|es$vi<=0))stop("nonfinite effect/variance",call.=FALSE)
fit<-metafor::rma.uni(yi=es$yi,vi=es$vi,method=if(p$model=="FE")"FE" else "REML",test="z",level=100*(1-alpha))
if(any(!is.finite(as.numeric(stats::coef(fit))))||!is.finite(as.numeric(fit$QE)))stop("single-group rma model did not return finite estimates",call.=FALSE)
pred<-stats::predict(fit,level=100*(1-alpha))
z<-stats::qnorm(1-alpha/2)
studies<-data.frame(study_id=d$study_id,cohort_id=d$cohort_id,events=d$events,denominator=d$denominator,
                    denominator_unit=d$denominator_unit,raw_value=if(p$measure=="proportion")d$events/d$denominator else d$events/d$denominator*scale,
                    yi=as.numeric(es$yi),vi=as.numeric(es$vi),display_estimate=inverse(as.numeric(es$yi)),
                    display_lower=inverse(as.numeric(es$yi)-z*sqrt(as.numeric(es$vi))),
                    display_upper=inverse(as.numeric(es$yi)+z*sqrt(as.numeric(es$vi))),
                    source_file=d$source_file,source_sha256=d$source_sha256,source_location=d$source_location)
write.csv(studies,file.path(out,"study_estimates.csv"),row.names=FALSE)
result<-data.frame(measure=p$measure,model=p$model,method=if(p$model=="FE")"inverse-variance FE" else "inverse-variance REML",
                   transformed_scale=if(p$measure=="proportion")"logit_proportion" else "log_incidence_rate",
                   display_unit=display_unit,n_studies=nrow(d),alpha=alpha,pooled_yi=as.numeric(pred$pred),
                   pooled_lower_yi=as.numeric(pred$ci.lb),pooled_upper_yi=as.numeric(pred$ci.ub),
                   pooled_display=inverse(as.numeric(pred$pred)),ci_lower=inverse(as.numeric(pred$ci.lb)),ci_upper=inverse(as.numeric(pred$ci.ub)),
                   Q=as.numeric(fit$QE),Q_df=as.numeric(fit$k-fit$p),Q_p=as.numeric(fit$QEp),I2=as.numeric(fit$I2),
                   tau2=if(p$model=="FE")0 else as.numeric(fit$tau2),tau2_status=if(p$model=="FE")"constrained_zero_FE" else "estimated_REML",
                   converged=TRUE,metafor_version=as.character(utils::packageVersion("metafor")))
write.csv(result,file.path(out,"single_summary.csv"),row.names=FALSE)
report<-c("# Single-group statistical facts","",paste("Source:",p$source_kind,"; studies:",nrow(d),"; measure:",p$measure),
          paste("Outcome:",p$outcome,"at",p$timepoint,"; event definition:",p$event_definition),
          paste("Denominator:",p$denominator_unit,"; display:",display_unit,"; model:",p$model,"; alpha:",alpha),
          paste("Pooled",display_unit,":",format(result$pooled_display,digits=8),"CI",format(result$ci_lower,digits=8),"to",format(result$ci_upper,digits=8)),
          paste("Q:",format(result$Q,digits=8),"I2:",format(result$I2,digits=8),"tau2:",format(result$tau2,digits=8),"(",result$tau2_status,")"),
          "No null-effect p-value is interpreted for a single-group prevalence or incidence rate. These are raw unadjusted counts; no rare-event or boundary correction is applied.",
          "Source locators and hashes check local consistency, not extraction accuracy or study independence concealed by labels. A statistical estimate is not a clinical conclusion or a complete review.")
writeLines(report,file.path(out,"fact_report.md"),useBytes=TRUE)
nr<-nrow(studies);height<-max(700,170+42*(nr+1))
png(file.path(out,"single_forest.png"),width=1150,height=height,res=130)
par(mar=c(5,11,4,3))
values<-c(studies$display_lower,studies$display_upper,result$ci_lower,result$ci_upper)
limits<-range(values);pad<-max(diff(limits)*.08,0.01)
plot(NA,xlim=c(limits[1]-pad,limits[2]+pad),ylim=c(0,nr+2),xlab=display_unit,ylab="",yaxt="n",
     main=paste("Single-group",gsub("_"," ",p$measure),"meta-analysis"))
axis(2,at=c(rev(seq_len(nr))+1,1),labels=c(studies$study_id,"Pooled"),las=1,tick=FALSE)
for(i in seq_len(nr)) {
  y<-nr+2-i
  segments(studies$display_lower[i],y,studies$display_upper[i],y,lwd=2)
  points(studies$display_estimate[i],y,pch=19,cex=.8)
}
segments(result$ci_lower,1,result$ci_upper,1,lwd=3,col="navy")
points(result$pooled_display,1,pch=18,cex=1.5,col="navy")
if(p$source_kind=="synthetic_fixture")mtext("SYNTHETIC DATA",side=3,line=.2,cex=.65)
dev.off()
