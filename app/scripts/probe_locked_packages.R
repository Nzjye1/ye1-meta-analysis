# Read-only namespace probe; base R only, no package installation or network.
a<-commandArgs(trailingOnly=TRUE)
if(length(a)<4)stop("Usage: probe_locked_packages.R LOCK_CSV OUTPUT_CSV STRICT_TARGET TARGET [SOURCE_LIBRARY...]",call.=FALSE)
lock<-read.csv(a[1],stringsAsFactors=FALSE)
strict<-identical(a[3],"YES");target<-a[4]
libs<-if(strict)target else unique(c(target,a[-seq_len(4)],.libPaths()))
libs<-libs[nzchar(libs)&dir.exists(libs)]
rows<-lapply(seq_len(nrow(lock)),function(i){
 name<-lock$name[i];expected<-lock$version[i];chosen<-"";version<-"";found<-character()
 for(lib in libs){
  desc<-file.path(lib,name,"DESCRIPTION")
  if(file.exists(desc)){
   info<-tryCatch(read.dcf(desc),error=function(e)NULL)
   if(!is.null(info)&&"Version"%in%colnames(info)){
    v<-info[1,"Version"];found<-c(found,paste0(v,"@",normalizePath(lib,winslash="/")))
    if(!nzchar(chosen)&&isTRUE(package_version(v)==package_version(expected))){chosen<-normalizePath(file.path(lib,name),winslash="/");version<-v}
   }
  }
 }
 data.frame(name=name,expected=expected,version=version,path=chosen,candidates=paste(found,collapse=" | "),stringsAsFactors=FALSE)
})
d<-do.call(rbind,rows)
.libPaths(unique(c(dirname(d$path[nzchar(d$path)]),.Library,.Library.site)))
d$load_ok<-FALSE;d$load_error<-""
for(i in seq_len(nrow(d))){
 if(nzchar(d$path[i])){
  name<-d$name[i]
  ok<-tryCatch({if(!requireNamespace(name,quietly=FALSE))stop("namespace load failed");TRUE},error=function(e){d$load_error[i]<<-conditionMessage(e);FALSE})
  if(ok){actual<-normalizePath(find.package(name),winslash="/");ok<-identical(actual,d$path[i]);if(!ok)d$load_error[i]<-paste("loaded unexpected path",actual)}
  d$load_ok[i]<-ok
 }
}
d$r_version<-as.character(getRversion());d$r_platform<-R.version$platform;d$r_arch<-R.version$arch
d$r_home<-normalizePath(R.home(),winslash="/")
d$r_system_libraries<-paste(normalizePath(c(.Library,.Library.site)[dir.exists(c(.Library,.Library.site))],winslash="/"),collapse="|")
write.csv(d,a[2],row.names=FALSE,na="")
