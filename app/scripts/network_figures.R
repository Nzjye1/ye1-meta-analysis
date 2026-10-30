# Readable generic figures, adapted from the BMJ 03b three-panel layout.
# Only checked contrasts and fitted results are used. No case-specific paths,
# hard-coded treatments, counts, axis limits, model labels or arm denominators.
network_figures <- function(d, reference, p, out) {
  title <- paste(p$model, p$tau_method, p$outcome, sep=" / ")
  n <- nrow(reference)
  draw_forest <- function() {
    layout(matrix(1:3, nrow=1), widths=c(.37,.34,.29))
    ys <- n:1
    limits <- range(c(0, reference$ci_lower, reference$ci_upper))
    pad <- max(diff(limits)*.08, .1)
    limits <- limits + c(-pad,pad)
    ratio <- p$effect_type %in% c("OR","RR")
    # Round log-ratio bounds outwards to standard powers of two. This retains
    # every CI while avoiding opaque exp(pretty(log(x))) axis labels.
    if(ratio) limits <- c(floor(limits[1]/log(2)),ceiling(limits[2]/log(2)))*log(2)
    par(mar=c(5,.6,4,0))
    plot.new(); plot.window(xlim=c(0,1), ylim=c(0,n+2))
    text(0,n+1.2,"Treatment",adj=0,font=2)
    text(0,ys,reference$treatment,adj=0,cex=.9)
    par(mar=c(5,0,4,0))
    plot.new(); plot.window(xlim=limits,ylim=c(0,n+2))
    abline(v=0,col="gray65",lty=2)
    segments(reference$ci_lower,ys,reference$ci_upper,ys,lwd=2,col="#1c5b7a")
    points(reference$estimate,ys,pch=15,col="#1c5b7a")
    ticks <- if(ratio) seq(limits[1]/log(2),limits[2]/log(2))*log(2) else pretty(limits)
    ticks <- ticks[ticks>=limits[1] & ticks<=limits[2]]
    axis(1,at=ticks,labels=format(signif(if(ratio) exp(ticks) else ticks,3),trim=TRUE))
    mtext(paste(p$effect_type,"versus",p$reference_treatment),1,3)
    par(mar=c(5,.6,4,1))
    plot.new();plot.window(xlim=c(0,1),ylim=c(0,n+2))
    text(0,n+1.2,paste0(p$effect_type," (",100*(1-p$alpha),"% CI)"),adj=0,font=2)
    label <- sprintf("%.3g (%.3g to %.3g)",reference$display_estimate,reference$display_lower,reference$display_upper)
    text(0,ys,label,adj=0,cex=.9)
    mtext(title,outer=TRUE,line=-1.5,font=2)
  }
  draw_network <- function() {
    treatments <- sort(unique(c(as.character(d$treat1),as.character(d$treat2))))
    nt <- length(treatments)
    angle <- seq(pi/2,pi/2+2*pi,length.out=nt+1)[seq_len(nt)]
    xy <- cbind(cos(angle),sin(angle)); rownames(xy) <- treatments
    codes <- setNames(sprintf("T%02d",seq_along(treatments)),treatments)
    edges <- unique(data.frame(study=d$study_id,
      a=pmin(as.character(d$treat1),as.character(d$treat2)),
      b=pmax(as.character(d$treat1),as.character(d$treat2))))
    edges <- aggregate(study~a+b,edges,length)
    counts <- vapply(treatments,function(t) length(unique(d$study_id[d$treat1==t | d$treat2==t])),integer(1))
    layout(matrix(1:2,nrow=1),widths=c(.52,.48))
    par(mar=c(4,1,4,1));plot.new();plot.window(xlim=c(-1.3,1.3),ylim=c(-1.3,1.3),asp=1)
    for(i in seq_len(nrow(edges))) segments(xy[edges$a[i],1],xy[edges$a[i],2],xy[edges$b[i],1],xy[edges$b[i],2],col=adjustcolor("#78909c",alpha.f=.5),lwd=.5+sqrt(edges$study[i]))
    points(xy,pch=21,bg=ifelse(treatments==p$reference_treatment,"#d66a34","#1c5b7a"),col="white",cex=2.7)
    text(xy[,1]*1.16,xy[,2]*1.16,codes,font=2,cex=.9)
    mtext("Equal-size nodes; edge width reflects study count",1,1.5,cex=.8)
    par(mar=c(4,0,4,1));plot.new();plot.window(xlim=c(0,1),ylim=c(0,nt+2))
    text(0,nt+1.2,"Treatment",adj=0,font=2);text(.96,nt+1.2,"Studies",adj=1,font=2)
    text(0,nt:1,paste(codes,treatments),adj=0,cex=.85);text(.96,nt:1,counts,adj=1,cex=.85)
    mtext(paste(length(unique(d$study_id)),"studies |",nt,"treatments |",nrow(edges),"direct edges"),outer=TRUE,line=-1.5,font=2)
  }
  for(kind in c("reference_forest","network_graph")) {
    draw <- if(kind=="reference_forest") draw_forest else draw_network
    height <- max(1250, 360+70*max(n,length(unique(c(d$treat1,d$treat2)))))
    png(file.path(out,paste0(kind,".png")),width=2400,height=height,res=160,pointsize=18)
    draw();dev.off()
    svg(file.path(out,paste0(kind,".svg")),width=15,height=height/160,pointsize=18)
    draw();dev.off()
  }
}
