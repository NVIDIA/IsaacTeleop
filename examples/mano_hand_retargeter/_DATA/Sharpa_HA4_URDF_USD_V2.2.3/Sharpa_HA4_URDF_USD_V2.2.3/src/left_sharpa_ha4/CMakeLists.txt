cmake_minimum_required(VERSION 3.5)
project(left_sharpa_ha4)

find_package(ament_cmake REQUIRED)

# Install resource directories
foreach(dir config launch meshes)
    install(DIRECTORY ${dir}/
        DESTINATION share/${PROJECT_NAME}/${dir})
endforeach()

install(FILES
    "left_sharpa_ha4_v2_1.urdf"
    "left_sharpa_ha4_v2_1.xml"
    DESTINATION share/${PROJECT_NAME}
)

ament_package()
