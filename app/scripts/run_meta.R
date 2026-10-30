args <- commandArgs(trailingOnly=TRUE)
if (length(args) != 3) stop("Usage: Rscript run_meta.R effects.csv analysis.csv NEW_OUTPUT_DIR", call.=FALSE)
input <- normalizePath(args[1], mustWork=TRUE)
planfile <- normalizePath(args[2], mustWork=TRUE)
out <- normalizePath(args[3], mustWork=FALSE)
if (file.exists(out)) stop("Output path already exists; choose a fresh directory", call.=FALSE)
script <- sub("^--file=", "", grep("^--file=", commandArgs(FALSE), value=TRUE)[1])
# Rscript encodes spaces in --file as ~+~ on this macOS runtime.
if (!file.exists(script)) script <- gsub("~+~", " ", script, fixed=TRUE)
root <- normalizePath(file.path(dirname(script), ".."), mustWork=TRUE)
source(file.path(root,"scripts","runtime_library.R"))
configure_meta_library(root)
if (!requireNamespace("metafor", quietly=TRUE)) stop("metafor missing; see README install instructions", call.=FALSE)

read_table <- function(path) read.csv(path, stringsAsFactors=FALSE, check.names=FALSE,
                                      na.strings=c("", "NA"), fileEncoding="UTF-8-BOM")
fail <- function(msg) stop(paste0("Validation: ", msg), call.=FALSE)
required_effect <- c("study_id","cohort_id","effect_type","estimate","ci_lower","ci_upper",
                     "outcome","timepoint","contrast","adjustment","source_document","source_location")
d <- read_table(input)
p <- read_table(planfile)
if (!all(required_effect %in% names(d))) fail(paste("missing effect columns:", paste(setdiff(required_effect,names(d)),collapse=", ")))
required_plan <- c("confirmed","effect_type","outcome","timepoint","contrast","adjustment",
                   "model","tau_method","test","alpha")
if (!all(required_plan %in% names(p)) || nrow(p)!=1) fail("analysis.csv requires exactly one row and all plan columns")
if (nrow(d)<2) fail("at least two independent study effects required")
for (nm in c(required_effect[!required_effect %in% c("estimate","ci_lower","ci_upper")])) {
  if (any(is.na(d[[nm]]) | !nzchar(trimws(d[[nm]])))) fail(paste("blank",nm))
}
for (nm in required_plan) if (is.na(p[[nm]][1]) || !nzchar(trimws(as.character(p[[nm]][1])))) fail(paste("blank plan",nm))
if (p$confirmed != "YES") fail("set confirmed=YES after checking effect scale, outcome, contrast, model, and source rows")
if (!(p$effect_type %in% c("RR","OR","HR","MD","SMD"))) fail("effect_type must be RR, OR, HR, MD, or SMD")
if (!(p$model %in% c("FE","RE"))) fail("model must be FE or RE")
if (!(p$tau_method %in% c("NONE","REML","DL"))) fail("tau_method must be NONE, REML or DL")
if ((p$model=="FE" && p$tau_method!="NONE") || (p$model=="RE" && !(p$tau_method %in% c("REML","DL")))) fail("model/tau_method mismatch")
if (p$test!="z") fail("only z test is implemented")
p$alpha <- suppressWarnings(as.numeric(p$alpha))
if (!is.finite(p$alpha) || p$alpha<=0 || p$alpha>=0.5) fail("alpha must be in (0,0.5)")
for (nm in c("effect_type","outcome","timepoint","contrast","adjustment")) {
  if (any(d[[nm]] != p[[nm]][1])) fail(paste("mixed or mismatched",nm,"; split analyses or resolve extraction"))
}
if (anyDuplicated(d$study_id)) fail("duplicate study_id: resolve multiple arms, timepoints, or reports")
if (anyDuplicated(d$cohort_id)) fail("duplicate cohort_id: possible overlapping cohort; resolve before pooling")
if (any(!grepl("(?i)(page|p\\.|table|figure|fig\\.)[[:space:]]*[A-Za-z0-9]",d$source_location,perl=TRUE))) fail("source_location requires explicit page, table, or figure identifier")
for (nm in c("estimate","ci_lower","ci_upper")) {
  d[[nm]] <- suppressWarnings(as.numeric(d[[nm]]))
  if (any(!is.finite(d[[nm]]))) fail(paste("nonfinite or invalid",nm))
}
if (p$effect_type %in% c("RR","OR","HR") && any(d$ci_lower<=0 | d$estimate<=0 | d$ci_upper<=0)) fail("ratio effect and CI must be positive")
if (any(d$ci_lower>=d$estimate | d$estimate>=d$ci_upper)) fail("CI must contain estimate strictly")
ratio <- p$effect_type %in% c("RR","OR","HR")
yi <- if (ratio) log(d$estimate) else d$estimate
lo <- if (ratio) log(d$ci_lower) else d$ci_lower
hi <- if (ratio) log(d$ci_upper) else d$ci_upper
zcrit <- qnorm(1-p$alpha/2)
sei <- (hi-lo)/(2*zcrit)
if (any(!is.finite(sei) | sei<=0)) fail("invalid derived standard error")
if (any(abs(yi-(lo+hi)/2) > pmax(0.03,0.15*sei))) fail("effect and CI are asymmetric on analysis scale; check adjusted estimate or rounding")
vi <- sei^2

fit <- metafor::rma.uni(yi=yi, vi=vi, method=if(p$model=="FE") "FE" else p$tau_method,
                        test="z", level=100*(1-p$alpha), slab=d$study_id)
trans <- if (ratio) exp else identity
ci <- c(as.numeric(fit$ci.lb),as.numeric(fit$ci.ub))
summary <- data.frame(effect_type=p$effect_type,model=p$model,tau_method=p$tau_method,
  test=p$test,alpha=p$alpha,k=fit$k,pooled=trans(as.numeric(fit$b)),
  ci_lower=trans(ci[1]),ci_upper=trans(ci[2]),p_value=fit$pval,
  Q=fit$QE,Q_df=fit$k-1,Q_p=fit$QEp,
  I2_percent=if(abs(fit$I2)<1e-8) 0 else fit$I2,tau2=fit$tau2)
studies <- d
studies$analysis_effect <- yi
studies$analysis_se <- sei
studies$analysis_variance <- vi
studies$weight_percent <- as.numeric(stats::weights(fit))

publish <- function(final_out) {
parent <- dirname(final_out)
if (!dir.exists(parent) && !dir.create(parent, recursive=TRUE, showWarnings=FALSE))
  stop("Cannot create output parent directory", call.=FALSE)
out <- tempfile(pattern=paste0(".", basename(final_out), ".pending-"), tmpdir=parent)
if (!dir.create(out)) stop("Cannot create temporary output directory", call.=FALSE)
on.exit(unlink(out, recursive=TRUE, force=TRUE), add=TRUE)
write.csv(studies,file.path(out,"study_effects_trace.csv"),row.names=FALSE,na="")
if (identical(Sys.getenv("META_TEST_FAIL_AFTER_FIRST_WRITE"), "1"))
  stop("Injected output failure for transaction test", call.=FALSE)
write.csv(summary,file.path(out,"pooled_result.csv"),row.names=FALSE)
if (nrow(d)>=3) {
  loo <- metafor::leave1out(fit)
  sensitivity <- data.frame(omitted_study=d$study_id,pooled=trans(loo$estimate),
                            ci_lower=trans(loo$ci.lb),ci_upper=trans(loo$ci.ub),
                            p_value=loo$pval,I2_percent=loo$I2)
  write.csv(sensitivity,file.path(out,"leave_one_out.csv"),row.names=FALSE)
}
ci_percent <- format(100*(1-p$alpha), trim=TRUE)
ci_header <- paste0("Effect [",ci_percent,"% CI]")
png(file.path(out,"forest.png"),width=1400,height=max(900,240+90*nrow(d)),res=150)
tryCatch({
  metafor::forest(fit, atransf=if(ratio) exp else NULL, xlab=paste0(p$effect_type," (",p$model,")"),
                  header=c("Study",ci_header))
}, finally=dev.off())
manifest <- data.frame(key=c("input_file","input_md5","analysis_file","analysis_md5",
                                 "script_md5","R_version","metafor_version","metafor_license","platform","forest_ci_header"),
                       value=c(input,unname(tools::md5sum(input)),planfile,unname(tools::md5sum(planfile)),
                               unname(tools::md5sum(script)),R.version.string,
                               as.character(packageVersion("metafor")),
                               packageDescription("metafor")$License,R.version$platform,ci_header))
if (!file.copy(planfile,file.path(out,"confirmed_analysis.csv"))) stop("Could not copy confirmed plan",call.=FALSE)
manifest <- rbind(manifest,data.frame(key=c("runtime_library_helper_md5","metafor_library_path","META_R_LIBRARY"),
 value=c(unname(tools::md5sum(file.path(root,"scripts","runtime_library.R"))),find.package("metafor"),Sys.getenv("META_R_LIBRARY"))))
write.csv(manifest,file.path(out,"reproducibility_manifest.csv"),row.names=FALSE)
fmt <- function(x) format(signif(x,5),trim=TRUE)
lines <- c("# Meta-analysis fact report", "",
  "Input is study-level extracted summary effects. No literature search, screening, extraction verification, or risk-of-bias judgment was performed by this run.","",
  paste0("- Analysis: ",p$outcome,"; ",p$timepoint,"; ",p$contrast,"; ",p$adjustment),
  paste0("- Effect: ",p$effect_type,"; model: ",p$model,"; tau estimator: ",p$tau_method,"; test: z; alpha: ",p$alpha),
  paste0("- Studies: ",fit$k),
  paste0("- Pooled ",p$effect_type,": ",fmt(summary$pooled)," (",ci_percent,"% CI ",fmt(summary$ci_lower)," to ",fmt(summary$ci_upper),"); p=",fmt(summary$p_value)),
  paste0("- Heterogeneity: Q=",fmt(summary$Q)," (df=",summary$Q_df,", p=",fmt(summary$Q_p),"); I²=",fmt(summary$I2_percent),"%; tau²=",fmt(summary$tau2)),
  "", "## Audit trail", "",
  "Study estimates and source page/table locations: study_effects_trace.csv. Analysis settings: supplied analysis.csv. Hashes and software versions: reproducibility_manifest.csv.",
  "Leave-one-out results are supplied when at least three studies are present. No publication or clinical conclusion is inferred from these numbers.")
writeLines(lines,file.path(out,"fact_report.md"),useBytes=TRUE)
expected <- c("study_effects_trace.csv","pooled_result.csv","forest.png",
              "confirmed_analysis.csv","reproducibility_manifest.csv","fact_report.md")
if (nrow(d)>=3) expected <- c(expected,"leave_one_out.csv")
paths <- file.path(out,expected)
if (any(!file.exists(paths)) || any(is.na(file.info(paths)$size) | file.info(paths)$size==0))
  stop("Incomplete output; final directory not committed", call.=FALSE)
if (file.exists(final_out) || !file.rename(out,final_out))
  stop("Could not commit complete output to fresh final directory", call.=FALSE)
cat("Wrote",final_out,"\n")
}
publish(out)
