check_diagmeta_lmer <- function(model) {
  if (!inherits(model, "merMod")) stop("diagmeta CICS fit did not return an lme4 model", call.=FALSE)
  opt <- model@optinfo$conv$opt
  if (length(opt)!=1 || is.na(opt) || as.integer(opt)!=0L)
    stop("diagmeta underlying optimizer did not report convergence", call.=FALSE)
  lme4_code <- model@optinfo$conv$lme4$code
  if (length(lme4_code)>0 && (any(is.na(lme4_code)) || any(as.integer(lme4_code)!=0L)))
    stop("diagmeta underlying lme4 convergence check failed", call.=FALSE)
  messages <- as.character(model@optinfo$conv$lme4$messages)
  messages <- messages[!is.na(messages) & nzchar(messages)]
  singular <- lme4::isSingular(model)
  boundary <- grepl("^boundary \\(singular\\) fit", messages)
  if (any(!boundary)) stop("diagmeta underlying lme4 convergence warning: ", paste(messages[!boundary],collapse="; "), call.=FALSE)
  list(status=if(singular) "converged_singular_boundary" else "converged_non_singular",
       optimizer_code=as.integer(opt), singular_boundary=singular,
       optimizer_messages=paste(messages,collapse="; "))
}
