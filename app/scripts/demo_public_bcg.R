args <- commandArgs(trailingOnly=TRUE)
if (length(args)!=1) stop("Usage: Rscript demo_public_bcg.R FRESH_OUTPUT_DIR",call.=FALSE)
target <- normalizePath(args[1],mustWork=FALSE)
if (file.exists(target)) stop("Output path exists",call.=FALSE)
script <- sub("^--file=", "", grep("^--file=",commandArgs(FALSE),value=TRUE)[1])
root <- normalizePath(file.path(dirname(script),".."),mustWork=TRUE)
source(file.path(root,"scripts","runtime_library.R"))
configure_meta_library(root)
if (!requireNamespace("metadat",quietly=TRUE) || !requireNamespace("metafor",quietly=TRUE))
  stop("Project-local metadat/metafor missing",call.=FALSE)
data("dat.bcg",package="metadat")
bcg <- dat.bcg
if (nrow(bcg)!=13 || any(bcg$tpos==0 | bcg$cpos==0))
  stop("Unexpected dat.bcg version; inspect before demo",call.=FALSE)
dir.create(target,recursive=TRUE)
raw <- data.frame(record_id=sprintf("PACKAGE-BCG-%02d",seq_len(nrow(bcg))),
  study_id=sprintf("PACKAGE-TRIAL-%02d",bcg$trial),
  cohort_id=sprintf("PACKAGE-COHORT-%02d",bcg$trial),
  input_type="binary",outcome="tuberculosis_event_package_example",
  timepoint="package_followup_not_harmonized",contrast="vaccinated_vs_control",
  adjustment="unadjusted",scale_direction="event_adverse",unit="none",value_basis="endpoint",
  source_document="metadat::dat.bcg package table, not original article verification",
  source_location=sprintf("table dat.bcg row %d",seq_len(nrow(bcg))),
  events_t=bcg$tpos,n_t=bcg$tpos+bcg$tneg,
  events_c=bcg$cpos,n_c=bcg$cpos+bcg$cneg,
  package_author=bcg$author,package_year=bcg$year)
write.csv(raw,file.path(target,"raw_package_data.csv"),row.names=FALSE)
derivation <- data.frame(confirmed="YES",input_type="binary",effect_type="RR",
  outcome=raw$outcome[1],timepoint=raw$timepoint[1],contrast=raw$contrast[1],
  adjustment="unadjusted",scale_direction="event_adverse",unit="none",value_basis="endpoint",
  alpha=.05,zero_policy="reject",continuity_add=0,continuity_to="none",
  smd_vtype=NA,smd_correct=NA)
plan <- data.frame(confirmed="YES",effect_type="RR",outcome=raw$outcome[1],
  timepoint=raw$timepoint[1],contrast=raw$contrast[1],adjustment="unadjusted",
  model="FE",tau_method="NONE",test="z",alpha=.05)
write.csv(derivation,file.path(target,"derivation.csv"),row.names=FALSE,na="")
write.csv(plan,file.path(target,"analysis.csv"),row.names=FALSE)
rscript <- file.path(R.home("bin"),"Rscript.exe")
if (!file.exists(rscript)) rscript <- file.path(R.home("bin"),"Rscript")
result <- system2(rscript,c(shQuote(file.path(root,"scripts","derive_effects.R")),
  shQuote(file.path(target,"raw_package_data.csv")),shQuote(file.path(target,"derivation.csv")),
  shQuote(file.path(target,"analysis.csv")),shQuote(file.path(target,"01_derived"))))
if (result!=0) stop("Derivation failed",call.=FALSE)
effects <- read.csv(file.path(target,"01_derived","derived_effects.csv"))
reference <- metafor::escalc(measure="RR",ai=bcg$tpos,bi=bcg$tneg,ci=bcg$cpos,di=bcg$cneg)
if (max(abs(log(effects$estimate)-as.numeric(reference$yi)))>1e-12)
  stop("Package example disagrees with documented escalc call",call.=FALSE)
# This first-row calculation is an independent arithmetic cross-check of the point estimate.
first_rr <- (bcg$tpos[1]/(bcg$tpos[1]+bcg$tneg[1])) /
            (bcg$cpos[1]/(bcg$cpos[1]+bcg$cneg[1]))
if (abs(effects$estimate[1]-first_rr)>1e-12) stop("Independent first-row RR mismatch",call.=FALSE)
write.csv(data.frame(key=c("dataset","package_version","package_license","source_url",
  "comparison","first_row_analytic_RR","original_articles_read","clinical_interpretation"),
  value=c("metadat::dat.bcg",as.character(packageVersion("metadat")),
  packageDescription("metadat")$License,"https://wviechtb.github.io/metadat/reference/dat.bcg.html",
  "13 effects matched metafor::escalc; first row independent arithmetic",first_rr,
  "NO","NO: follow-up and study design are not harmonized here")),
  file.path(target,"public_example_validation.csv"),row.names=FALSE)
result <- system2(rscript,c(shQuote(file.path(root,"scripts","run_meta.R")),
  shQuote(file.path(target,"01_derived","derived_effects.csv")),
  shQuote(file.path(target,"analysis.csv")),shQuote(file.path(target,"02_numeric_analysis"))))
if (result!=0) stop("Numeric analysis failed",call.=FALSE)
cat("PUBLIC PACKAGE EXAMPLE PASS:",target,"\n")
