cmake_minimum_required(VERSION 3.5)
project(right_sharpa_ha4)

find_package(ament_cmake REQUIRED)

# Install resource directories
foreach(dir config launch meshes)
    install(DIRECTORY ${dir}/
        DESTINATION share/${PROJECT_NAME}/${dir})
endforeach()

install(FILES
    "right_sharpa_ha4_v2_1.urdf"
    "right_sharpa_ha4_v2_1.xml"
    DESTINATION share/${PROJECT_NAME}
)

ament_package()
