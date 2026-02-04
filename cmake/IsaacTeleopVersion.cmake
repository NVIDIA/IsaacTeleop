# Read base version from file and set the patch equal to the number of git commits
# since the last change to the version file.
# - version_file: Path to the base version file containing MAJOR.MINOR.x
# - out_var: Name of the CMake variable in the caller's scope that will receive
#   the computed version string (MAJOR.MINOR.x becomes MAJOR.MINOR.#COMMITS)
function(isaac_teleop_read_version version_file out_var)
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

	string(REGEX MATCH "^([0-9]+)\\.([0-9]+)\\.x" _isaac_teleop_version_match "${_isaac_teleop_version_base}")
	if(NOT _isaac_teleop_version_match)
		message(FATAL_ERROR "Base version must be in MAJOR.MINOR.x format; actual content: '${_isaac_teleop_version_base}'")
	endif()
	set(_isaac_teleop_version_major "${CMAKE_MATCH_1}")
	set(_isaac_teleop_version_minor "${CMAKE_MATCH_2}")
	set(_isaac_teleop_version_patch "${_isaac_teleop_git_count}")
	set(_isaac_teleop_version "${_isaac_teleop_version_major}.${_isaac_teleop_version_minor}.${_isaac_teleop_version_patch}")

	set(${out_var} "${_isaac_teleop_version}" PARENT_SCOPE)
	message(STATUS "IsaacTeleop version: ${_isaac_teleop_version} (base ${_isaac_teleop_version_base}, +${_isaac_teleop_git_count} commits)")
endfunction()
