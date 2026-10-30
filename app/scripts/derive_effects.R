args <- commandArgs(trailingOnly=TRUE)
if (!(length(args) %in% c(4,5)))
  stop("Usage: Rscript derive_effects.R raw.csv derivation.csv analysis.csv FRESH_OUT_DIR [FRESH_FAILURE_DIR]",call.=FALSE)

derive <- function(args) {
  raw_path <- normalizePath(args[1],mustWork=TRUE)
  config_path <- normalizePath(args[2],mustWork=TRUE)
  analysis_path <- normalizePath(args[3],mustWork=TRUE)
  final_out <- normalizePath(args[4],mustWork=FALSE)
  if (file.exists(final_out)) stop("Output path already exists",call.=FALSE)
  script <- sub("^--file=", "", grep("^--file=",commandArgs(FALSE),value=TRUE)[1])
  root <- normalizePath(file.path(dirname(script),".."),mustWork=TRUE)
  source(file.path(root,"scripts","runtime_library.R"))
  configure_meta_library(root)
  if (!requireNamespace("metafor",quietly=TRUE) || !requireNamespace("digest",quietly=TRUE))
    stop("Project-local metafor/digest dependency missing",call.=FALSE)
  sha256 <- function(path) digest::digest(readBin(path,"raw",n=file.info(path)$size),
                                          serialize=FALSE,algo="sha256")
  read_table <- function(path) read.csv(path,stringsAsFactors=FALSE,check.names=FALSE,
                                        na.strings=c("","NA"),fileEncoding="UTF-8-BOM")
  require_fields <- function(x,fields,label) {
    missing <- setdiff(fields,names(x))
    if (length(missing)) stop(paste(label,"missing columns:",paste(missing,collapse=",")),call.=FALSE)
  }
  nonblank <- function(x) !is.na(x) & nzchar(trimws(as.character(x)))
  raw <- read_table(raw_path)
  cfg <- read_table(config_path)
  plan <- read_table(analysis_path)
  common <- c("record_id","study_id","cohort_id","input_type","outcome","timepoint","contrast",
              "adjustment","scale_direction","unit","value_basis","source_document","source_location")
  config_fields <- c("confirmed","input_type","effect_type","outcome","timepoint","contrast",
                     "adjustment","scale_direction","unit","value_basis","alpha","zero_policy",
                     "continuity_add","continuity_to","smd_vtype","smd_correct")
  plan_fields <- c("confirmed","effect_type","outcome","timepoint","contrast","adjustment","alpha")
  require_fields(raw,common,"raw.csv")
  require_fields(cfg,config_fields,"derivation.csv")
  require_fields(plan,plan_fields,"analysis.csv")
  if (nrow(raw)<2 || nrow(cfg)!=1 || nrow(plan)!=1) stop("Need at least two raw rows and one row per config",call.=FALSE)
  cfg <- cfg[1,,drop=FALSE]; plan <- plan[1,,drop=FALSE]
  if (cfg$confirmed!="YES" || plan$confirmed!="YES")
    stop("Both derivation and analysis plans require confirmed=YES",call.=FALSE)
  if (!(cfg$input_type %in% c("binary","continuous"))) stop("input_type must be binary or continuous",call.=FALSE)
  if (!(cfg$effect_type %in% c("RR","OR","MD","SMD"))) stop("Only RR/OR from binary and MD/SMD from continuous are supported",call.=FALSE)
  if (cfg$input_type=="binary" && !(cfg$effect_type %in% c("RR","OR")) ||
      cfg$input_type=="continuous" && !(cfg$effect_type %in% c("MD","SMD")))
    stop("input_type/effect_type mismatch",call.=FALSE)
  for (field in c("effect_type","outcome","timepoint","contrast","adjustment"))
    if (as.character(cfg[[field]]) != as.character(plan[[field]]))
      stop(paste("derivation and analysis disagree on",field),call.=FALSE)
  cfg$alpha <- suppressWarnings(as.numeric(cfg$alpha))
  plan$alpha <- suppressWarnings(as.numeric(plan$alpha))
  if (!is.finite(cfg$alpha) || cfg$alpha<=0 || cfg$alpha>=0.5 ||
      !is.finite(plan$alpha) || abs(cfg$alpha-plan$alpha)>1e-12)
    stop("alpha invalid or inconsistent with analysis plan",call.=FALSE)
  for (field in c("input_type","outcome","timepoint","contrast","adjustment",
                  "scale_direction","unit","value_basis")) {
    if (field=="unit" && cfg$effect_type=="SMD") next
    if (any(is.na(raw[[field]]) | as.character(raw[[field]])!=as.character(cfg[[field]])))
      stop(paste("mixed or mismatched",field),call.=FALSE)
  }
  for (field in common)
    if (any(!nonblank(raw[[field]]))) stop(paste("blank",field),call.=FALSE)
  if (anyDuplicated(raw$study_id) || anyDuplicated(raw$cohort_id))
    stop("repeated study_id or cohort_id; resolve dependent effects",call.=FALSE)
  if (cfg$adjustment!="unadjusted" || cfg$value_basis!="endpoint")
    stop("Raw two-group conversion supports unadjusted independent endpoint data only",call.=FALSE)
  if (any(!grepl("(?i)(page|p\\.|table|figure|fig\\.)[[:space:]]*[A-Za-z0-9]",
                 raw$source_location,perl=TRUE)))
    stop("Each raw row needs a page/table/figure source locator",call.=FALSE)
  if (cfg$input_type=="binary") {
    if (!(cfg$scale_direction %in% c("event_adverse","event_benefit")))
      stop("Binary scale_direction must be event_adverse or event_benefit",call.=FALSE)
    if (cfg$unit!="none") stop("Binary unit must be none",call.=FALSE)
    require_fields(raw,c("events_t","n_t","events_c","n_c"),"binary raw.csv")
    for (field in c("events_t","n_t","events_c","n_c")) {
      raw[[field]] <- suppressWarnings(as.numeric(raw[[field]]))
      if (any(!is.finite(raw[[field]]) | raw[[field]]<0 | raw[[field]]!=floor(raw[[field]])))
        stop(paste("invalid nonnegative integer",field),call.=FALSE)
    }
    if (any(raw$n_t<=0 | raw$n_c<=0 | raw$events_t>raw$n_t | raw$events_c>raw$n_c))
      stop("Binary events must not exceed positive group totals",call.=FALSE)
    if (any(raw$events_t==0 & raw$events_c==0) ||
        any(raw$events_t==raw$n_t & raw$events_c==raw$n_c))
      stop("Double-zero or double-all-event study requires separate adjudication; none silently dropped",call.=FALSE)
    if (!(cfg$zero_policy %in% c("reject","continuity_0.5_only0")))
      stop("zero_policy must be reject or continuity_0.5_only0",call.=FALSE)
    if (cfg$zero_policy=="reject") {
      if (cfg$continuity_add!=0 || cfg$continuity_to!="none")
        stop("reject policy requires continuity_add=0 and continuity_to=none",call.=FALSE)
      if (any(raw$events_t==0 | raw$events_c==0 | raw$events_t==raw$n_t | raw$events_c==raw$n_c))
        stop("Zero cell found under reject policy",call.=FALSE)
      add <- 0; to <- "none"
    } else {
      if (cfg$continuity_add!=0.5 || cfg$continuity_to!="only0")
        stop("continuity policy requires add=0.5 to=only0",call.=FALSE)
      add <- 0.5; to <- "only0"
    }
    if (!is.na(cfg$smd_vtype) || !is.na(cfg$smd_correct))
      stop("SMD parameters must be NA for binary input",call.=FALSE)
    es <- metafor::escalc(measure=as.character(cfg$effect_type),ai=raw$events_t,
       bi=raw$n_t-raw$events_t,ci=raw$events_c,di=raw$n_c-raw$events_c,
       add=add,to=to,drop00=FALSE)
    vtype <- "NA"; smd_correct <- "NA"
  } else {
    if (!(cfg$scale_direction %in% c("higher_is_better","lower_is_better")))
      stop("Continuous scale_direction must state higher/lower is better",call.=FALSE)
    if (cfg$effect_type=="MD" && (!nonblank(cfg$unit) || cfg$unit=="multiple_allowed"))
      stop("MD requires one common declared unit",call.=FALSE)
    if (cfg$effect_type=="SMD" && cfg$unit!="multiple_allowed")
      stop("SMD unit setting must be multiple_allowed; scale direction still must agree",call.=FALSE)
    require_fields(raw,c("n_t","mean_t","sd_t","n_c","mean_c","sd_c"),"continuous raw.csv")
    for (field in c("n_t","mean_t","sd_t","n_c","mean_c","sd_c")) {
      raw[[field]] <- suppressWarnings(as.numeric(raw[[field]]))
      if (any(!is.finite(raw[[field]]))) stop(paste("nonfinite",field),call.=FALSE)
    }
    if (any(raw$n_t<2 | raw$n_c<2 | raw$n_t!=floor(raw$n_t) | raw$n_c!=floor(raw$n_c) |
            raw$sd_t<=0 | raw$sd_c<=0))
      stop("Continuous group sizes must be integers >=2 and SDs positive",call.=FALSE)
    if (!is.na(cfg$zero_policy) || !is.na(cfg$continuity_add) || !is.na(cfg$continuity_to))
      stop("Zero-cell parameters must be NA for continuous input",call.=FALSE)
    if (cfg$effect_type=="SMD") {
      if (cfg$smd_vtype!="LS" || cfg$smd_correct!="TRUE")
        stop("SMD slice requires vtype=LS and Hedges correction TRUE",call.=FALSE)
      es <- metafor::escalc(measure="SMD",m1i=raw$mean_t,sd1i=raw$sd_t,n1i=raw$n_t,
         m2i=raw$mean_c,sd2i=raw$sd_c,n2i=raw$n_c,vtype="LS",correct=TRUE)
      vtype <- "LS"; smd_correct <- "TRUE"
    } else {
      if (!is.na(cfg$smd_vtype) || !is.na(cfg$smd_correct))
        stop("SMD parameters must be NA for MD input",call.=FALSE)
      es <- metafor::escalc(measure="MD",m1i=raw$mean_t,sd1i=raw$sd_t,n1i=raw$n_t,
         m2i=raw$mean_c,sd2i=raw$sd_c,n2i=raw$n_c)
      vtype <- "NA"; smd_correct <- "NA"
    }
    add <- NA_real_; to <- "NA"
  }
  yi <- as.numeric(es$yi); vi <- as.numeric(es$vi)
  if (any(!is.finite(yi) | !is.finite(vi) | vi<=0))
    stop("metafor::escalc returned missing/nonpositive variance; no rows exported",call.=FALSE)
  z <- qnorm(1-cfg$alpha/2)
  ratio <- cfg$effect_type %in% c("RR","OR")
  transform <- if (ratio) exp else identity
  effects <- raw[,c("record_id","study_id","cohort_id"),drop=FALSE]
  effects$effect_type <- as.character(cfg$effect_type)
  effects$estimate <- transform(yi)
  effects$ci_lower <- transform(yi-z*sqrt(vi))
  effects$ci_upper <- transform(yi+z*sqrt(vi))
  for (field in c("outcome","timepoint","contrast","adjustment","source_document","source_location"))
    effects[[field]] <- raw[[field]]
  effects$derivation_method <- "metafor::escalc"
  effects$derivation_measure <- as.character(cfg$effect_type)
  effects$derivation_vtype <- vtype
  effects$derivation_smd_correct <- smd_correct
  effects$derivation_zero_policy <- as.character(cfg$zero_policy)
  effects$derivation_continuity_add <- add
  effects$derivation_continuity_to <- to
  effects$derivation_input_row <- seq_len(nrow(raw))+1L
  effects$derivation_input_sha256 <- sha256(raw_path)
  effects$derivation_config_sha256 <- sha256(config_path)
  effects$scale_direction <- raw$scale_direction
  effects$unit <- raw$unit
  effects$value_basis <- raw$value_basis
  trace <- raw
  trace$raw_input_row <- seq_len(nrow(raw))+1L
  trace$yi <- yi; trace$vi <- vi; trace$sei <- sqrt(vi)
  trace$engine <- "metafor::escalc"
  trace$measure <- as.character(cfg$effect_type)
  trace$zero_policy <- as.character(cfg$zero_policy)
  trace$continuity_add <- add
  trace$continuity_to <- to
  trace$smd_vtype <- vtype
  trace$smd_correct <- smd_correct
  parent <- dirname(final_out)
  if (!dir.exists(parent) && !dir.create(parent,recursive=TRUE,showWarnings=FALSE))
    stop("Cannot create output parent",call.=FALSE)
  pending <- tempfile(pattern=paste0(".",basename(final_out),".pending-"),tmpdir=parent)
  if (!dir.create(pending)) stop("Cannot create temporary output",call.=FALSE)
  on.exit(unlink(pending,recursive=TRUE,force=TRUE),add=TRUE)
  write.csv(effects,file.path(pending,"derived_effects.csv"),row.names=FALSE,na="")
  write.csv(trace,file.path(pending,"derivation_trace.csv"),row.names=FALSE,na="")
  receipt <- data.frame(key=c("status","raw_sha256","derivation_sha256","analysis_sha256",
       "derived_effects_sha256","R_version","metafor_version","metafor_license",
       "measure","effect_scale","zero_policy","continuity_add","continuity_to","smd_vtype","smd_correct"),
       value=c("SUCCESS",sha256(raw_path),
       sha256(config_path),sha256(analysis_path),
       sha256(file.path(pending,"derived_effects.csv")),
       R.version.string,as.character(packageVersion("metafor")),packageDescription("metafor")$License,
       as.character(cfg$effect_type),if(ratio)"log ratio; displayed as ratio" else "linear",
       as.character(cfg$zero_policy),as.character(add),to,vtype,smd_correct))
  receipt<-rbind(receipt,data.frame(key=c("metafor_library_path","META_R_LIBRARY"),value=c(find.package("metafor"),Sys.getenv("META_R_LIBRARY"))))
  write.csv(receipt,file.path(pending,"derivation_receipt.csv"),row.names=FALSE)
  expected <- file.path(pending,c("derived_effects.csv","derivation_trace.csv","derivation_receipt.csv"))
  if (any(!file.exists(expected)) || any(file.info(expected)$size<=0))
    stop("Incomplete derivation output",call.=FALSE)
  if (file.exists(final_out) || !file.rename(pending,final_out))
    stop("Cannot commit derivation output",call.=FALSE)
  cat("Derived",nrow(effects),as.character(cfg$effect_type),"effects to",final_out,"\n")
}

tryCatch(derive(args),error=function(e) {
  reason <- conditionMessage(e)
  if (length(args)==5 && !file.exists(args[5])) {
    dir.create(args[5],recursive=TRUE,showWarnings=FALSE)
    if (dir.exists(args[5])) {
      value <- c("FAILED",reason)
      key <- c("status","reason")
      for (i in 1:3) if (file.exists(args[i])) {
        key <- c(key,paste0("input",i,"_md5"))
        value <- c(value,unname(tools::md5sum(args[i])))
      }
      write.csv(data.frame(key=key,value=value),file.path(args[5],"failure_receipt.csv"),row.names=FALSE)
    }
  }
  cat("Validation:",reason,"\n",file=stderr())
  quit(save="no",status=2)
})
