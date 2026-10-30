# Local native binaries only; repos=NULL disables repository access.
a<-commandArgs(trailingOnly=TRUE)
if(length(a)<2)stop("Usage: install_cached_native.R PRIVATE_STAGE ARCHIVE...",call.=FALSE)
if(!dir.exists(a[1])||!all(file.exists(a[-1])))stop("Private stage or cached archive missing",call.=FALSE)
kind<-if(.Platform$OS.type=="windows")"win.binary" else if(Sys.info()[["sysname"]]=="Darwin")"mac.binary" else stop("Untested binary platform",call.=FALSE)
.libPaths(c(a[1],.libPaths()))
install.packages(a[-1],lib=a[1],repos=NULL,type=kind,dependencies=FALSE)
