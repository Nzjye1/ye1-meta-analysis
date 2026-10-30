# Resolve a deliberately configured private library without installing or copying packages.
configure_meta_library <- function(root) {
  supplied <- Sys.getenv("META_R_LIBRARY", unset="")
  selected <- if (nzchar(supplied)) supplied else file.path(root,"r-library")
  if (nzchar(supplied) && !dir.exists(selected))
    stop("META_R_LIBRARY does not exist; set it to a native, compatible private R library",call.=FALSE)
  if (dir.exists(selected)) .libPaths(c(normalizePath(selected),.libPaths()))
  invisible(.libPaths())
}
