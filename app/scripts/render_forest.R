# Presentation only: draw stored estimates/intervals; never fit or recalculate a model.
a <- commandArgs(trailingOnly=TRUE)
if(length(a)!=6) stop("Usage: render_forest.R TRACE POOLED OUTPUT UNIT DIRECTION LABEL",call.=FALSE)
d<-read.csv(a[1],check.names=FALSE);p<-read.csv(a[2],check.names=FALSE)
ratio<-p$effect_type %in% c("RR","OR","HR")
transform<-if(ratio) log else identity
lo<-transform(d$ci_lower);hi<-transform(d$ci_upper);est<-transform(d$estimate)
pl<-transform(p$ci_lower);ph<-transform(p$ci_upper);pe<-transform(p$pooled)
lim<-range(c(lo,hi,pl,ph));span<-diff(lim);if(span==0)span<-1
n<-nrow(d);xlim<-lim+c(-1.4,1.1)*span
png(a[3],width=1600,height=max(1000,400+70*n),res=170)
tryCatch({
 par(mar=c(7,2,4,2));plot(NA,xlim=xlim,ylim=c(-1,n+2),axes=FALSE,xlab="",ylab="")
 ticks<-pretty(lim);axis(1,at=ticks,labels=format(if(ratio)exp(ticks) else ticks,digits=3))
 abline(v=if(ratio)0 else 0,col="grey70",lty=2)
 text(xlim[1],n+1.5,"Study",adj=0,font=2)
 text(xlim[2],n+1.5,sprintf("%s [%.0f%% CI]",p$effect_type,100*(1-p$alpha)),adj=1,font=2)
 for(i in seq_len(n)){y<-n-i+1;segments(lo[i],y,hi[i],y);points(est[i],y,pch=15,cex=1.1)
 text(xlim[1],y,d$study_id[i],adj=0);text(xlim[2],y,sprintf("%.2f [%.2f, %.2f]",d$estimate[i],d$ci_lower[i],d$ci_upper[i]),adj=1)}
 polygon(c(pl,pe,ph,pe),c(0,.22,0,-.22),col="#264c70",border="#264c70")
 text(xlim[1],0,paste("Pooled",p$model),adj=0,font=2)
 text(xlim[2],0,sprintf("%.2f [%.2f, %.2f]",p$pooled,p$ci_lower,p$ci_upper),adj=1,font=2)
 title(main=a[6],xlab=paste(p$effect_type,if(nzchar(a[4]))paste0(" (",a[4],")") else ""))
 mtext(a[5],side=1,line=4,cex=.75)
},finally=dev.off())
