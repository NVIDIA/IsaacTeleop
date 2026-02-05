# Read base version from file and set the patch equal to the number of git commits
# since the last change to the version file.
# - version_file: Path to the base version file containing MAJOR.MINOR.x
# - out_cmake_version_var: Name of the CMake variable in the caller's scope that will receive
#   the computed CMake version string (MAJOR.MINOR[.#PATCH])
# - out_pyproject_version_var: Name of the CMake variable in the caller's scope that will receive
#   the computed PEP 440 Python version string that is computed as follows:
#   * Release (CI + tag vX.Y.Z): tag must match computed version; Python version is X.Y.Z, no label/local.
#   * Alpha (CI + main): Python version X.Y.PATCHa, no local.
#   * Dev (CI + feature branch): Python version X.Y.PATCH.dev+branchlabel (sanitized).
#   * RC (CI + branch release/X.Y.x): branch must match base version; Python version X.Y.PATCHrc, no local.
#   * Local working copy (non-CI): Python version X.Y+local and CMake version X.Y (patch omitted).
function(isaac_teleop_read_version version_file out_cmake_version_var out_pyproject_version_var)
	find_package(Git REQUIRED)
	get_filename_component(_isaac_teleop_version_file "${version_file}" ABSOLUTE)
	if(NOT EXISTS "${_isaac_teleop_version_file}")
		message(FATAL_ERROR "Version file not found: ${_isaac_teleop_version_file}")
	endif()
	file(READ "${_isaac_teleop_version_file}" _isaac_teleop_version_base)
	string(STRIP "${_isaac_teleop_version_base}" _isaac_teleop_version_base)

	execute_process(
		COMMAND "${GIT_EXECUTABLE}" -C "${CMAKE_CURRENT_SOURCE_DIR}" rev-parse --show-toplevel
		OUTPUT_VARIABLE _isaac_teleop_git_root
		OUTPUT_STRIP_TRAILING_WHITESPACE
		ERROR_QUIET
		RESULT_VARIABLE _isaac_teleop_git_root_result
	)
	if(NOT _isaac_teleop_git_root_result EQUAL 0 OR _isaac_teleop_git_root STREQUAL "")
		message(FATAL_ERROR "Failed to determine git root. Ensure this is a git repository and git is available.")
	endif()
	execute_process(
		COMMAND "${GIT_EXECUTABLE}" -C "${_isaac_teleop_git_root}" rev-list -n 1 HEAD -- "${_isaac_teleop_version_file}"
		OUTPUT_VARIABLE _isaac_teleop_version_commit
		OUTPUT_STRIP_TRAILING_WHITESPACE
		ERROR_QUIET
		RESULT_VARIABLE _isaac_teleop_version_commit_result
	)
	if(NOT _isaac_teleop_version_commit_result EQUAL 0 OR _isaac_teleop_version_commit STREQUAL "")
		message(FATAL_ERROR "Failed to locate last commit for version file: ${_isaac_teleop_version_file}")
	endif()
	execute_process(
		COMMAND "${GIT_EXECUTABLE}" -C "${_isaac_teleop_git_root}" rev-list --count "${_isaac_teleop_version_commit}..HEAD"
		OUTPUT_VARIABLE _isaac_teleop_git_count
		OUTPUT_STRIP_TRAILING_WHITESPACE
		ERROR_QUIET
		RESULT_VARIABLE _isaac_teleop_git_count_result
	)
	if(NOT _isaac_teleop_git_count_result EQUAL 0)
		message(FATAL_ERROR "Failed to count commits since ${_isaac_teleop_version_commit}.")
	endif()
	if(NOT _isaac_teleop_git_count MATCHES "^[0-9]+$")
		message(FATAL_ERROR "Invalid git commit count: '${_isaac_teleop_git_count}'")
	endif()

	execute_process(
		COMMAND "${GIT_EXECUTABLE}" -C "${_isaac_teleop_git_root}" rev-parse --abbrev-ref HEAD
		OUTPUT_VARIABLE _isaac_teleop_git_branch
		OUTPUT_STRIP_TRAILING_WHITESPACE
		ERROR_QUIET
		RESULT_VARIABLE _isaac_teleop_git_branch_result
	)
	if(NOT _isaac_teleop_git_branch_result EQUAL 0 OR _isaac_teleop_git_branch STREQUAL "")
		message(FATAL_ERROR "Failed to determine git branch name.")
	endif()
	if(_isaac_teleop_git_branch STREQUAL "HEAD")
		if(DEFINED ENV{GITHUB_REF_NAME} AND NOT "$ENV{GITHUB_REF_NAME}" STREQUAL "")
			set(_isaac_teleop_git_branch "$ENV{GITHUB_REF_NAME}")
		elseif(DEFINED ENV{GITHUB_HEAD_REF} AND NOT "$ENV{GITHUB_HEAD_REF}" STREQUAL "")
			set(_isaac_teleop_git_branch "$ENV{GITHUB_HEAD_REF}")
		elseif(DEFINED ENV{CI_COMMIT_REF_NAME} AND NOT "$ENV{CI_COMMIT_REF_NAME}" STREQUAL "")
			set(_isaac_teleop_git_branch "$ENV{CI_COMMIT_REF_NAME}")
		endif()
	endif()

	execute_process(
		COMMAND "${GIT_EXECUTABLE}" -C "${_isaac_teleop_git_root}" describe --tags --exact-match
		OUTPUT_VARIABLE _isaac_teleop_git_tag
		OUTPUT_STRIP_TRAILING_WHITESPACE
		ERROR_QUIET
		RESULT_VARIABLE _isaac_teleop_git_tag_result
	)
	if(NOT _isaac_teleop_git_tag_result EQUAL 0)
		set(_isaac_teleop_git_tag "")
	endif()

	string(REGEX MATCH "^([0-9]+)\\.([0-9]+)\\.x" _isaac_teleop_version_match "${_isaac_teleop_version_base}")
	if(NOT _isaac_teleop_version_match)
		message(FATAL_ERROR "Base version must be in MAJOR.MINOR.x format; actual content: '${_isaac_teleop_version_base}'")
	endif()
	set(_isaac_teleop_version_major "${CMAKE_MATCH_1}")
	set(_isaac_teleop_version_minor "${CMAKE_MATCH_2}")
	set(_isaac_teleop_version_patch "${_isaac_teleop_git_count}")
	set(_isaac_teleop_version "${_isaac_teleop_version_major}.${_isaac_teleop_version_minor}.${_isaac_teleop_version_patch}")

	set(_isaac_teleop_is_ci FALSE)
	if(DEFINED ENV{CI} AND NOT "$ENV{CI}" STREQUAL "")
		string(TOLOWER "$ENV{CI}" _isaac_teleop_ci_value)
		if(NOT _isaac_teleop_ci_value STREQUAL "0" AND NOT _isaac_teleop_ci_value STREQUAL "false")
			set(_isaac_teleop_is_ci TRUE)
		endif()
	endif()

	set(_isaac_teleop_pyproject_version "")
	set(_isaac_teleop_build_kind "local")

	if(_isaac_teleop_is_ci AND NOT _isaac_teleop_git_tag STREQUAL "")
		if(NOT _isaac_teleop_git_tag MATCHES "^v([0-9]+)\\.([0-9]+)\\.([0-9]+)$")
			message(FATAL_ERROR "Invalid release tag format: '${_isaac_teleop_git_tag}' (expected vMAJOR.MINOR.PATCH)")
		endif()
		set(_isaac_teleop_tag_version "${CMAKE_MATCH_1}.${CMAKE_MATCH_2}.${CMAKE_MATCH_3}")
		if(NOT _isaac_teleop_tag_version STREQUAL "${_isaac_teleop_version}")
			message(FATAL_ERROR "Release tag ${_isaac_teleop_git_tag} does not match calculated version ${_isaac_teleop_version}.")
		endif()
		set(_isaac_teleop_pyproject_version "${_isaac_teleop_tag_version}")
		set(_isaac_teleop_build_kind "release")
	elseif(_isaac_teleop_is_ci AND _isaac_teleop_git_branch MATCHES "^release/([0-9]+)\\.([0-9]+)\\.x$")
		if(NOT "${CMAKE_MATCH_1}" STREQUAL "${_isaac_teleop_version_major}" OR NOT "${CMAKE_MATCH_2}" STREQUAL "${_isaac_teleop_version_minor}")
			message(FATAL_ERROR "Release branch ${_isaac_teleop_git_branch} does not match base version ${_isaac_teleop_version_base}.")
		endif()
		set(_isaac_teleop_pyproject_version "${_isaac_teleop_version_major}.${_isaac_teleop_version_minor}.${_isaac_teleop_version_patch}rc1")
		set(_isaac_teleop_build_kind "rc")
	elseif(_isaac_teleop_is_ci AND _isaac_teleop_git_branch STREQUAL "main")
		set(_isaac_teleop_pyproject_version "${_isaac_teleop_version_major}.${_isaac_teleop_version_minor}.${_isaac_teleop_version_patch}a1")
		set(_isaac_teleop_build_kind "alpha")
	elseif(_isaac_teleop_is_ci)
		string(TOLOWER "${_isaac_teleop_git_branch}" _isaac_teleop_label)
		string(REGEX REPLACE "[^a-z0-9._-]" "." _isaac_teleop_label "${_isaac_teleop_label}") # replace disallowed chars with dots
		string(REGEX REPLACE "[._-]+" "." _isaac_teleop_label "${_isaac_teleop_label}") # collapse separator runs to a single dot
		string(REGEX REPLACE "^[._-]+" "" _isaac_teleop_label "${_isaac_teleop_label}") # trim leading separators
		string(REGEX REPLACE "[._-]+$" "" _isaac_teleop_label "${_isaac_teleop_label}") # trim trailing separators
		if(_isaac_teleop_label STREQUAL "")
			set(_isaac_teleop_label "unknown")
		endif()
		set(_isaac_teleop_pyproject_version "${_isaac_teleop_version_major}.${_isaac_teleop_version_minor}.${_isaac_teleop_version_patch}.dev0+${_isaac_teleop_label}")
		set(_isaac_teleop_build_kind "dev")
	else()
		set(_isaac_teleop_pyproject_version "${_isaac_teleop_version_major}.${_isaac_teleop_version_minor}+local")
		set(_isaac_teleop_build_kind "local")
		set(_isaac_teleop_version "${_isaac_teleop_version_major}.${_isaac_teleop_version_minor}")
	endif()

	set(${out_cmake_version_var} "${_isaac_teleop_version}" PARENT_SCOPE)
	set(${out_pyproject_version_var} "${_isaac_teleop_pyproject_version}" PARENT_SCOPE)
	message(STATUS "IsaacTeleop version: ${_isaac_teleop_version} (${_isaac_teleop_version_base} + ${_isaac_teleop_git_count} commits) python: ${_isaac_teleop_pyproject_version} kind: ${_isaac_teleop_build_kind}")
endfunction()
