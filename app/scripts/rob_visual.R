args<-commandArgs(trailingOnly=TRUE)
if(length(args)!=2)stop("Usage: rob_visual.R AUDIT_CSV OUTPUT_PNG",call.=FALSE)
d<-read.csv(args[1],check.names=FALSE,fileEncoding="UTF-8-BOM",stringsAsFactors=FALSE)
if(!all(c("study_id","design_type","domain","judgment") %in% names(d)) || nrow(d)<1)
  stop("checked RoB audit lacks required rows",call.=FALSE)
studies<-unique(d$study_id);domains<-unique(d$domain)
if(length(studies)>50 || length(domains)>20)stop("visualization size limit",call.=FALSE)
labels<-c(low="#2E8540",some_concerns="#E3B341",high="#B6423C",
          moderate="#E3B341",serious="#D76B3F",critical="#9B3137",
          no_information="#AAB2BD",unclear="#AAB2BD")
if(any(!d$judgment %in% names(labels)))stop("unsupported reviewed judgment",call.=FALSE)
png(args[2],width=max(1700,300+210*length(domains)),height=max(1000,420+85*length(studies)),res=150)
par(mar=c(13,12,8,3),xpd=NA)
plot(NA,xlim=c(0,length(domains)),ylim=c(0,length(studies)),xlab="",ylab="",axes=FALSE,
     main="Reviewer-entered risk-of-bias judgments (local draft)")
for(i in seq_along(studies))for(j in seq_along(domains)){
  row<-d[d$study_id==studies[i] & d$domain==domains[j],]
  if(nrow(row)>1)stop("duplicate study/domain judgment",call.=FALSE)
  fill<-if(nrow(row))labels[row$judgment[1]] else "#FFFFFF"
  rect(j-1,length(studies)-i,j,length(studies)-i+1,col=fill,border="#68717B")
  if(nrow(row))text(j-.5,length(studies)-i+.5,gsub("_"," ",row$judgment[1]),cex=.63)
}
axis(1,at=seq_along(domains)-.5,labels=gsub("_"," ",domains),las=2,tick=FALSE,cex.axis=.7)
axis(2,at=length(studies)-seq_along(studies)+.5,labels=studies,las=1,tick=FALSE,cex.axis=.8)
mtext("Judgments and domain names are user supplied; colors are display only, not instrument scoring.",side=3,line=.6,cex=.7)
dev.off()
cat("ROB_VISUAL",length(studies),length(domains),"\n")
