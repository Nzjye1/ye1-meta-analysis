args<-commandArgs(trailingOnly=TRUE)
if(length(args)!=3)stop("Usage: rare_events.R CHECKED_INPUT ENGINE_PLAN OUTPUT_DIR",call.=FALSE)
script<-sub("^--file=","",grep("^--file=",commandArgs(FALSE),value=TRUE)[1])
if(!file.exists(script))script<-gsub("~+~"," ",script,fixed=TRUE)
root<-normalizePath(file.path(dirname(script),".."),mustWork=TRUE)
source(file.path(root,"scripts","runtime_library.R"));configure_meta_library(root)
if(!requireNamespace("metafor",quietly=TRUE))stop("metafor unavailable",call.=FALSE)
d<-read.csv(args[1],check.names=FALSE,fileEncoding="UTF-8-BOM",stringsAsFactors=FALSE)
p<-read.csv(args[2],check.names=FALSE,fileEncoding="UTF-8-BOM",stringsAsFactors=FALSE)
if(nrow(p)!=1 || nrow(d)<1)stop("invalid checked data/plan",call.=FALSE)
p<-p[1,];p$peto_sensitivity<-tolower(as.character(p$peto_sensitivity))=="true"
p$cmh_test_correction<-tolower(as.character(p$cmh_test_correction))=="true"
out<-normalizePath(args[3],mustWork=TRUE)
measure<-p$effect_type;level<-100*(1-as.numeric(p$alpha));z<-stats::qnorm(1-as.numeric(p$alpha)/2)
pooled_add<-if(p$pooled_MH_correction=="revman_0.5")0.5 else 0
individual_label<-"0.5 to all four cells of studies with any zero cell; arm totals +1"
pooled_label<-if(pooled_add==0)"none" else individual_label
warnings<-data.frame(context=character(),kind=character(),message=character())
record<-function(context,kind,message) {
  warnings<<-rbind(warnings,data.frame(context=context,kind=kind,message=message))
}
capture<-function(expr,context) {
  tryCatch(withCallingHandlers(expr,warning=function(w) {
    record(context,"warning",conditionMessage(w));invokeRestart("muffleWarning")
  }),error=function(e) {record(context,"not_estimable",conditionMessage(e));NULL})
}
triplet<-function(fit) {
  if(is.null(fit))return(rep(NA_real_,3))
  value<-exp(c(as.numeric(fit$b),fit$ci.lb,fit$ci.ub))
  if(length(value)!=3 || any(!is.finite(value)) || any(value<=0))return(rep(NA_real_,3))
  value
}
analyze<-function(data,context) {
  zero<-data$events_t==0 & data$events_c==0
  boundary_all<-data$events_t==data$n_t & data$events_c==data$n_c
  keep<-!(zero|boundary_all);x<-data[keep,,drop=FALSE];k<-nrow(x)
  ai<-x$events_t;bi<-x$n_t-ai;ci<-x$events_c;di<-x$n_c-ci
  any_zero<-ai==0 | bi==0 | ci==0 | di==0
  es<-if(k)capture(metafor::escalc(measure=measure,ai=ai,bi=bi,ci=ci,di=di,
       add=.5,to="only0",drop00=FALSE),paste(context,"individual")) else NULL
  # Two-element arguments control study effects and MH pooling separately.
  # correct is the CMH test switch, never the pooled RR/OR correction switch.
  fit<-if(k)capture(metafor::rma.mh(ai=ai,bi=bi,ci=ci,di=di,measure=measure,
       add=c(.5,pooled_add),to=c("only0",if(pooled_add==0)"none" else "only0"),
       drop00=c(FALSE,FALSE),correct=p$cmh_test_correction,level=level,slab=x$study_id),
       paste(context,"MH")) else NULL
  mh<-triplet(fit);estimable<-all(is.finite(mh))
  status<-if(!k)"NOT_ESTIMABLE_NO_INFORMATIVE_STUDIES" else if(!estimable)"NOT_ESTIMABLE_MH" else
    if(k==1)"SINGLE_STUDY_ESTIMABLE" else "ESTIMABLE"
  if(k && !estimable)record(context,"not_estimable","Configured MH has no finite positive ratio and interval; corrected individual effects are separate, not a substitute.")
  good_es<-k>0 && !is.null(es) && all(is.finite(es$yi)&is.finite(es$vi)&es$vi>0)
  iv<-if(good_es)capture(metafor::rma.uni(yi=es$yi,vi=es$vi,method="FE",test="z",level=level),paste(context,"IV sensitivity")) else NULL
  iv_value<-triplet(iv)
  # MH denominator contributions, not the inverse-variance weights used in Q.
  delta<-pooled_add*any_zero
  a<-ai+delta;b<-bi+delta;c<-ci+delta;dd<-di+delta
  n1<-a+b;n2<-c+dd;N<-n1+n2
  mh_w<-if(measure=="RR")c*n1/N else b*c/N
  mh_num<-if(measure=="RR")a*n2/N else a*dd/N
  iv_w<-if(good_es)1/es$vi else rep(NA_real_,k)
  Q<-Q_p<-I2<-NA_real_;df<-if(k>=2)k-1 else NA_integer_
  heterogeneity_status<-if(k<2)"NOT_APPLICABLE_FEWER_THAN_TWO_STUDIES" else if(!estimable || !good_es)"NOT_ESTIMABLE" else "ESTIMABLE"
  if(heterogeneity_status=="ESTIMABLE") {
    # RevMan algorithms: IV weights centered on the MH log estimate.
    Q<-sum(iv_w*(es$yi-log(mh[1]))^2)
    Q_p<-stats::pchisq(Q,df=df,lower.tail=FALSE)
    I2<-if(Q==0)0 else max(0,(Q-df)/Q)*100
  }
  list(x=x,zero=zero,all=boundary_all,keep=keep,k=k,es=es,fit=fit,mh=mh,iv=iv_value,
       any_zero=any_zero,mh_w=mh_w,mh_num=mh_num,iv_w=iv_w,status=status,
       Q=Q,Q_p=Q_p,I2=I2,df=df,heterogeneity_status=heterogeneity_status)
}
r<-analyze(d,"primary");keep<-r$keep;x<-r$x;k<-r$k
trace<-data.frame(record_id=d$record_id,study_id=d$study_id,events_t=d$events_t,n_t=d$n_t,
  events_c=d$events_c,n_c=d$n_c,source_file=d$source_file,source_sha256=d$source_sha256,
  source_location=d$source_location,in_relative_pool=keep,
  exclusion_reason=ifelse(r$zero,"both arms zero events",ifelse(r$all,"both arms all events","")),
  individual_effect_correction=p$individual_effect_correction,pooled_MH_correction=p$pooled_MH_correction,
  double_zero_policy=p$double_zero_policy,display_correction=ifelse(keep,individual_label,"not plotted"),
  individual_correction_applied=FALSE,pooled_correction_applied=FALSE,
  study_ratio=NA_real_,study_ci_lower=NA_real_,study_ci_upper=NA_real_,
  mh_numerator_contribution=NA_real_,mh_weight=NA_real_,mh_weight_percent=NA_real_,
  q_iv_weight=NA_real_,q_iv_weight_percent=NA_real_)
if(k) {
  trace$individual_correction_applied[keep]<-r$any_zero
  trace$pooled_correction_applied[keep]<-r$any_zero & pooled_add>0
  trace$study_ratio[keep]<-exp(r$es$yi)
  trace$study_ci_lower[keep]<-exp(r$es$yi-z*sqrt(r$es$vi))
  trace$study_ci_upper[keep]<-exp(r$es$yi+z*sqrt(r$es$vi))
  trace$mh_numerator_contribution[keep]<-r$mh_num
  trace$mh_weight[keep]<-r$mh_w
  if(sum(r$mh_w)>0)trace$mh_weight_percent[keep]<-100*r$mh_w/sum(r$mh_w)
  trace$q_iv_weight[keep]<-r$iv_w
  if(all(is.finite(r$iv_w)))trace$q_iv_weight_percent[keep]<-100*r$iv_w/sum(r$iv_w)
}
write.csv(trace,file.path(out,"study_trace.csv"),row.names=FALSE,na="")
assess<-rep(NA_real_,3)
if(p$peto_sensitivity && measure=="OR" && k)assess<-triplet(capture(metafor::rma.peto(
  ai=x$events_t,bi=x$n_t-x$events_t,ci=x$events_c,di=x$n_c-x$events_c,
  add=0,to="none",drop00=FALSE,level=level,slab=x$study_id),"primary Peto"))
arm_balance<-if(k)max(pmax(x$n_t/x$n_c,x$n_c/x$n_t)) else NA_real_
event_fraction<-if(k)sum(x$events_t+x$events_c)/sum(x$n_t+x$n_c) else NA_real_
peto_warning<-if(!p$peto_sensitivity)"not requested" else if(!k)"no informative studies" else
  paste(c(if(arm_balance>1.5)"arms materially imbalanced" else NULL,
          if(event_fraction>=.05)"overall events not below 5%" else NULL,
          if(is.finite(assess[1]) && (assess[1]<.5 || assess[1]>2))"observed Peto OR far from 1" else NULL),collapse="; ")
if(p$peto_sensitivity && peto_warning=="")peto_warning<-"conditions screened; Peto still exploratory"
result<-data.frame(effect_type=measure,model="Mantel-Haenszel fixed effect",alpha=p$alpha,
  estimation_status=r$status,k_identified=nrow(d),k_informative=k,k_double_zero=sum(r$zero),k_double_all=sum(r$all),
  mh_ratio=r$mh[1],mh_ci_lower=r$mh[2],mh_ci_upper=r$mh[3],
  mh_p_value=if(all(is.finite(r$mh)))r$fit$pval else NA_real_,
  Q=r$Q,Q_df=r$df,Q_p=r$Q_p,I2_percent=r$I2,tau2=if(k)0 else NA_real_,
  tau2_status="FIXED_MODEL_ASSUMED_ZERO_NOT_ESTIMATED",
  heterogeneity_status=r$heterogeneity_status,heterogeneity_center="configured MH log ratio",
  heterogeneity_weights="inverse individual log-variance; separate from MH pooling weights",
  iv_corrected_ratio=r$iv[1],iv_corrected_ci_lower=r$iv[2],iv_corrected_ci_upper=r$iv[3],
  peto_ratio=assess[1],peto_ci_lower=assess[2],peto_ci_upper=assess[3],
  peto_status=if(!p$peto_sensitivity)"NOT_REQUESTED" else if(!is.finite(assess[1]))"NOT_ESTIMABLE" else "SENSITIVITY_ONLY",
  peto_warning=peto_warning,max_arm_ratio=arm_balance,pooled_event_fraction=event_fraction,
  individual_effect_correction=p$individual_effect_correction,pooled_MH_correction=p$pooled_MH_correction,
  double_zero_policy=p$double_zero_policy,cmh_test_correction=p$cmh_test_correction,
  mh_zero_correction=pooled_label,individual_display_and_iv_correction=individual_label,
  double_boundary_policy="double-zero and double-all excluded with source trace",
  metafor_add=paste(.5,pooled_add,sep=";"),metafor_to=paste("only0",if(pooled_add==0)"none" else "only0",sep=";"),
  metafor_drop00="FALSE;FALSE (boundary exclusions applied before fit)",
  interval_method="two-sided normal interval on log ratio; exponentiated",
  mh_variance_method=if(measure=="RR")"Greenland-Robins MH log RR" else "Robins-Breslow-Greenland MH log OR",
  R_version=R.version.string,
  metafor_version=as.character(utils::packageVersion("metafor")))
write.csv(result,file.path(out,"rare_summary.csv"),row.names=FALSE,na="")
loo<-do.call(rbind,lapply(seq_len(nrow(d)),function(i) {
  rr<-analyze(d[-i,,drop=FALSE],paste("leave_one_out",d$study_id[i]))
  data.frame(omitted_study=d$study_id[i],k_remaining=nrow(d)-1,k_informative=rr$k,
    estimation_status=rr$status,mh_ratio=rr$mh[1],mh_ci_lower=rr$mh[2],mh_ci_upper=rr$mh[3],
    single_study_display_ratio=if(rr$k==1)exp(rr$es$yi[1]) else NA_real_,
    single_study_display_ci_lower=if(rr$k==1)exp(rr$es$yi[1]-z*sqrt(rr$es$vi[1])) else NA_real_,
    single_study_display_ci_upper=if(rr$k==1)exp(rr$es$yi[1]+z*sqrt(rr$es$vi[1])) else NA_real_,
    Q=rr$Q,Q_df=rr$df,Q_p=rr$Q_p,I2_percent=rr$I2,heterogeneity_status=rr$heterogeneity_status,
    individual_effect_correction=p$individual_effect_correction,pooled_MH_correction=p$pooled_MH_correction,
    double_zero_policy=p$double_zero_policy)
}))
write.csv(loo,file.path(out,"rare_leave_one_out.csv"),row.names=FALSE,na="")
write.csv(warnings,file.path(out,"engine_warnings.csv"),row.names=FALSE,na="")
number<-function(v)ifelse(is.finite(v),format(v,digits=6),"not estimable / not applicable")
report<-c("# Rare-event pairwise statistical facts","",
  paste("Effect",measure,"; outcome",p$outcome,"at",p$timepoint,"; comparator",p$contrast),
  paste("Identified",nrow(d),"; informative",k,"; double-zero",sum(r$zero),"; double-all",sum(r$all)),
  paste("Configured MH status:",r$status,"; ratio",number(r$mh[1]),"CI",number(r$mh[2]),"to",number(r$mh[3])),
  paste("individual_effect_correction:",p$individual_effect_correction,"-",individual_label),
  paste("pooled_MH_correction:",p$pooled_MH_correction,"-",pooled_label),
  paste("double_zero_policy:",p$double_zero_policy,"(also excludes both arms all events; source rows retained)"),
  paste("metafor add:",result$metafor_add,"; to:",result$metafor_to,"; drop00:",result$metafor_drop00),
  paste("CMH test correction:",p$cmh_test_correction,"; this is not a pooled RR/OR correction switch."),
  paste("Heterogeneity:",r$heterogeneity_status,"; MH-centered Q",number(r$Q),"df",number(r$df),"p",number(r$Q_p),"I2 (%)",number(r$I2)),
  "Q uses inverse-variance weights of corrected individual log effects, centered on the configured MH log estimate. These are not MH pooling weights. tau2=0 is a fixed-model assumption, not an estimated absence of heterogeneity.",
  "study_trace.csv exports MH denominator contributions and normalized MH weights (RR: c*n1/N; OR: b*c/N), numerator contributions, and separate Q IV weights. A zero denominator contribution can still have a nonzero numerator contribution.",
  paste("IV FE sensitivity",number(r$iv[1]),"CI",number(r$iv[2]),"to",number(r$iv[3]),"; uses the individual correction, not the pooled MH policy."),
  paste("Peto status",result$peto_status,"; warning",peto_warning),
  "The default retains uncorrected MH pooling. revman_0.5 is an explicit RevMan-compatible configuration: 0.5 to all four cells in a study with any zero, arm totals +1, double-zero/all excluded. It is not evidence of the authors' original project settings.",
  "Leave-one-out retains the selected configuration and includes omission of excluded studies. With one informative study the configured MH effect is reported if estimable; heterogeneity is not applicable. Corrected single-study display values are separate fields. Non-estimable MH values and intervals are blank, not replaced by finite corrected display intervals.",
  paste("Engine conditions recorded:",nrow(warnings),"in engine_warnings.csv; full child output retained in engine_stdout.txt and engine_stderr.txt."),
  "Double-boundary source rows, raw counts and source hashes remain in the local trace. This conditional aggregate reanalysis does not verify clinical independence, source extraction or a complete systematic review.",
  "Algorithm references: https://wviechtb.github.io/metafor/reference/rma.mh.html ; https://training.cochrane.org/handbook/current/statistical-methods-revman5")
writeLines(report,file.path(out,"fact_report.md"),useBytes=TRUE)
draw<-function(file,point,lower,upper,labels,title,subtitle,weights=NULL) {
  png(file.path(out,file),width=1450,height=max(850,330+100*length(labels)),res=200)
  on.exit(dev.off())
  valid<-is.finite(point)&is.finite(lower)&is.finite(upper)&point>0&lower>0&upper>0
  lim<-range(c(1,lower[valid],upper[valid]),finite=TRUE)
  if(diff(lim)==0)lim<-c(.5,2)
  lim<-exp(log(lim)+c(-.15,.15)*max(diff(log(lim)),.5))
  par(mar=c(7.5,10,5,2));plot(NA,xlim=lim,ylim=c(0,length(labels)+1),log="x",xlab="",
    ylab="",yaxt="n",main=title)
  at<-rev(seq_along(labels));axis(2,at=at,labels=labels,las=1,tick=FALSE,cex.axis=.85)
  abline(v=1,col="gray60",lty=2)
  for(i in seq_along(labels)) {
    if(valid[i]) {
      segments(lower[i],at[i],upper[i],at[i],lwd=2)
      size<-if(is.null(weights) || !is.finite(weights[i]))1 else .5+sqrt(max(0,weights[i]))/5
      points(point[i],at[i],pch=if(i==length(labels)&&file=="rare_forest.png")18 else 15,cex=size,col="navy")
    } else text(1,at[i],"not estimable",cex=.65,pos=4)
  }
  mtext(paste(measure,"ratio"),side=1,line=2.7,cex=1)
  mtext(subtitle,side=1,line=4.4,cex=.75)
  mtext(paste("Study effects: four-cell 0.5 if any zero; pooled MH:",p$pooled_MH_correction),side=3,line=.3,cex=.75)
  if(p$source_kind=="synthetic_fixture")mtext("SYNTHETIC DATA",side=1,line=6.1,cex=.7)
}
draw("rare_forest.png",c(trace$study_ratio[keep],r$mh[1]),c(trace$study_ci_lower[keep],r$mh[2]),
     c(trace$study_ci_upper[keep],r$mh[3]),c(x$study_id,if(k==1)"MH single study" else "MH pooled"),
     paste("MH;",k,"informative;",sum(!keep),"double-boundary excluded"),
     "Square sizes: MH denominator weights. Q uses separate IV weights.",
     c(trace$mh_weight_percent[keep],NA_real_))
draw("rare_leave_one_out.png",loo$mh_ratio,loo$mh_ci_lower,loo$mh_ci_upper,paste("Omit",loo$omitted_study),
     "Leave-one-out: configured MH", "Single-study heterogeneity: not applicable. Non-estimable MH is labeled.")
cat("DONE",k,measure,r$status,"; conditions",nrow(warnings),"\n")
