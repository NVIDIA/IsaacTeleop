from launch import LaunchDescription
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory
import os

def generate_launch_description():
    pkg_share = get_package_share_directory('right_sharpa_ha4')  # <-- match your ROS2 package name
    urdf_file = os.path.join(pkg_share, 'right_sharpa_ha4_v2_1.urdf')

    return LaunchDescription([
        # Start Gazebo empty world
        Node(
            package='gazebo_ros',
            executable='gazebo',
            output='screen',
            arguments=['-s', 'libgazebo_ros_factory.so']
        ),

        # Static transform base_link -> base_footprint
        Node(
            package='tf2_ros',
            executable='static_transform_publisher',
            arguments=['0', '0', '0', '0', '0', '0', 'base_link', 'base_footprint']
        ),

        # Spawn URDF model into Gazebo
        Node(
            package='gazebo_ros',
            executable='spawn_entity.py',
            arguments=['-file', urdf_file, '-entity', 'Right_Sharpa_HA4'],
            output='screen'
        )

        # ROS2 doesn’t really have a built-in launch equivalent for:
        # rostopic pub /calibrated std_msgs/Bool true
        # If you still need that, you’d create a small Python node to publish it.
    ])
