args<-commandArgs(trailingOnly=TRUE)
if(length(args)!=3)stop("Usage: dependent_effects.R EFFECTS PLAN OUT",call.=FALSE)
script<-sub("^--file=","",grep("^--file=",commandArgs(FALSE),value=TRUE)[1])
if(!file.exists(script))script<-gsub("~+~"," ",script,fixed=TRUE)
root<-normalizePath(file.path(dirname(script),".."),mustWork=TRUE)
.libPaths(c(file.path(root,"method-r-library"),file.path(root,"r-library"),.libPaths()))
if(!requireNamespace("metafor",quietly=TRUE)||!requireNamespace("clubSandwich",quietly=TRUE))
  stop("project-private metafor and clubSandwich required",call.=FALSE)
d<-read.csv(args[1],stringsAsFactors=FALSE,check.names=FALSE,fileEncoding="UTF-8-BOM")
p<-as.list(read.csv(args[2],stringsAsFactors=FALSE,check.names=FALSE,fileEncoding="UTF-8-BOM")[1,,drop=FALSE])
out<-normalizePath(args[3],mustWork=TRUE)
if(nrow(d)<4||p$model!="rma.mv_nested_REML_CR2"||!(p$effect_type %in% c("RR","OR","HR","MD","SMD")))stop("invalid checked dependent plan",call.=FALSE)
rho_values<-as.numeric(strsplit(as.character(p$rho_values),"|",fixed=TRUE)[[1]])
primary<-as.numeric(p$primary_rho);alpha<-as.numeric(p$alpha)
if(length(rho_values)<2||any(!is.finite(rho_values))||any(rho_values<0|rho_values>=.95)||!(primary %in% rho_values)||!is.finite(alpha)||alpha<=0||alpha>=.5)
  stop("invalid working correlations/alpha",call.=FALSE)
ratio<-p$effect_type %in% c("RR","OR","HR")
if(p$input_scale!=if(ratio)"log_ratio" else "linear")stop("effect input scale invalid",call.=FALSE)
if(any(!is.finite(d$estimate)|!is.finite(d$se)|d$se<=0))stop("invalid effects/SEs",call.=FALSE)
ids<-unique(d$study_id);n<-nrow(d)
V_for<-function(rho) {
  V<-matrix(0,n,n)
  for(sid in ids) {
    index<-which(d$study_id==sid);se<-d$se[index]
    block<-rho*outer(se,se);diag(block)<-se^2
    if(min(eigen(block,symmetric=TRUE,only.values=TRUE)$values)<=0)stop("working covariance not positive definite",call.=FALSE)
    V[index,index]<-block
  }
  V
}
back<-function(x)if(ratio)exp(x)else x
results<-list();primary_v<-NULL;primary_fit<-NULL;primary_interval<-NULL
for(i in seq_along(rho_values)) {
  rho<-rho_values[i];V<-V_for(rho)
  fit<-metafor::rma.mv(yi=d$estimate,V=V,random=~1|study_id/effect_id,data=d,method="REML",test="z")
  test<-clubSandwich::coef_test(fit,vcov="CR2",cluster=d$study_id,test="Satterthwaite")
  interval<-clubSandwich::conf_int(fit,vcov="CR2",cluster=d$study_id,test="Satterthwaite",level=1-alpha)
  if(nrow(test)!=1||nrow(interval)!=1||!all(c("beta","SE","df_Satt","p_Satt") %in% names(test))||
     !all(c("CI_L","CI_U") %in% names(interval)))stop("CR2 inference columns unavailable",call.=FALSE)
  beta<-as.numeric(test$beta[1]);robust_se<-as.numeric(test$SE[1]);df<-as.numeric(test$df_Satt[1])
  lower<-as.numeric(interval$CI_L[1]);upper<-as.numeric(interval$CI_U[1])
  if(any(!is.finite(c(beta,robust_se,df,lower,upper)))||robust_se<=0||df<=0||lower>upper)stop("CR2 inference non-estimable",call.=FALSE)
  results[[i]]<-data.frame(rho=rho,primary=rho==primary,n_studies=length(ids),n_effects=n,
                           beta=beta,robust_se=robust_se,df_satterthwaite=df,p_value=as.numeric(test$p_Satt[1]),
                           ci_lower=lower,ci_upper=upper,display_estimate=back(beta),display_lower=back(lower),display_upper=back(upper),
                           sigma2_study=as.numeric(fit$sigma2[1]),sigma2_effect=as.numeric(fit$sigma2[2]),
                           inference_status="CR2_SATTERTHWAITE",low_cluster_warning=length(ids)<10,
                           metafor_version=as.character(utils::packageVersion("metafor")),clubSandwich_version=as.character(utils::packageVersion("clubSandwich")))
  if(rho==primary){primary_v<-V;primary_fit<-fit;primary_interval<-c(lower,upper)}
}
result<-do.call(rbind,results)
write.csv(result,file.path(out,"dependent_results.csv"),row.names=FALSE)
cov_rows<-list()
for(j in seq_along(ids)) {
  idx<-which(d$study_id==ids[j]);block<-primary_v[idx,idx,drop=FALSE]
  cov_rows[[j]]<-data.frame(study_id=ids[j],row_effect=rep(d$effect_id[idx],each=length(idx)),
                            column_effect=rep(d$effect_id[idx],times=length(idx)),
                            covariance=as.vector(t(block)),assumed_rho=primary)
}
write.csv(do.call(rbind,cov_rows),file.path(out,"working_covariance.csv"),row.names=FALSE)
write.csv(d,file.path(out,"effect_trace.csv"),row.names=FALSE)
selected<-result[result$primary,,drop=FALSE]
report<-c("# Dependent-effect statistical facts","",paste("Source:",p$source_kind,"; independent study clusters:",length(ids),"; correlated effects:",n),
          paste("Effect:",p$effect_type,"on",p$input_scale,"scale; outcome:",p$outcome,"at",p$timepoint),
          paste("Dependency rationale:",p$dependency_rationale),
          paste("Primary assumed within-study sampling correlation:",primary,"; sensitivity grid:",paste(rho_values,collapse=", ")),
          paste("Nested rma.mv REML pooled estimate:",format(selected$display_estimate,digits=8),"CR2/Satterthwaite CI:",format(selected$display_lower,digits=8),"to",format(selected$display_upper,digits=8),"df:",format(selected$df_satterthwaite,digits=7)),
          "The working equicorrelation is an assumption, not estimated from these summary rows. CR2 adjusts inference for study clusters; it does not prove that hidden cohorts are independent or make heterogenous outcomes exchangeable.",
          "Small-cluster warnings and all rho sensitivity estimates must be reviewed. Local source hashes check consistency only. This is not a causal or final clinical conclusion.")
writeLines(report,file.path(out,"fact_report.md"),useBytes=TRUE)
est<-back(d$estimate);z<-stats::qnorm(1-alpha/2);lo<-back(d$estimate-z*d$se);hi<-back(d$estimate+z*d$se)
height<-max(750,180+38*(n+1))
png(file.path(out,"dependent_forest.png"),width=1200,height=height,res=130)
par(mar=c(5,12,4,3));limits<-range(c(lo,hi,selected$display_lower,selected$display_upper));pad<-max(diff(limits)*.06,.01)
plot(NA,xlim=c(limits[1]-pad,limits[2]+pad),ylim=c(0,n+2),xlab=if(ratio)p$effect_type else p$effect_type,
     ylab="",yaxt="n",main=paste("Dependent effects; primary rho",primary))
axis(2,at=c(rev(seq_len(n))+1,1),labels=c(paste(d$study_id,d$effect_id,sep=" / "),"Pooled CR2"),las=1,tick=FALSE)
for(i in seq_len(n)){y<-n+2-i;segments(lo[i],y,hi[i],y,lwd=1.5);points(est[i],y,pch=19,cex=.65)}
segments(selected$display_lower,1,selected$display_upper,1,lwd=3,col="navy");points(selected$display_estimate,1,pch=18,cex=1.5,col="navy")
if(ratio)abline(v=1,lty=2,col="gray50")else abline(v=0,lty=2,col="gray50")
if(p$source_kind=="synthetic_fixture")mtext("SYNTHETIC DATA",side=3,line=.2,cex=.65)
dev.off()
png(file.path(out,"rho_sensitivity.png"),width=1000,height=760,res=130)
par(mar=c(5,6,4,2));limits<-range(c(result$display_lower,result$display_upper));pad<-max(diff(limits)*.08,.01)
plot(result$rho,result$display_estimate,type="b",pch=19,lwd=2,ylim=c(limits[1]-pad,limits[2]+pad),
     xlab="Assumed within-study sampling correlation",ylab=if(ratio)p$effect_type else p$effect_type,main="Working-correlation sensitivity")
segments(result$rho,result$display_lower,result$rho,result$display_upper,col="navy",lwd=2)
points(primary,selected$display_estimate,pch=18,cex=1.4,col="red3")
if(p$source_kind=="synthetic_fixture")mtext("SYNTHETIC DATA",side=3,line=.2,cex=.65)
dev.off()
