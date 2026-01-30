# Sharpa HA4 Hand URDF and XML Files

## Model Description

1. All model files under the `meshes` folder are simplified versions. If you need to modify the models for use, please contact lei.su@sharpa.com.  
2. Each fingertip has three coordinate frames:  
   - `XXX_DP` frame: satisfies the MDH convention,  
   - `XXX_elastomer` frame: used for tactile sensors,  
   - `XXX_fingertip` frame: used for IK fingertip position annotation.  
   Please choose according to your needs.

## Dynamics Parameter Description

### Isaac Lab Dynamics
1. The dynamics parameters for Isaac Lab have already been configured in the USD files. You can directly use `IdealPDActuator` with both `stiffness` and `damping` set to `None`.  
2. The calibration method uses simulated trajectories to align with the trajectories of the real hardware.

### XML Parameter Description
1. Currently, `armature`, `frictionloss`, `actuatorfrcrange`, and `damping` are set based on Isaac Gym calibration results. These may not be fully accurate for dynamics and will be refined in future work.  
2. For rigid body collision parameters, everything is set to default except for the fingertip elastomer, which has a modified `solref` to make it softer and more elastic. Please contact lei.su@sharpa.com if you notice any issues.  
3. MuJoCo dynamics parameters have not yet been calibrated. If you need to use them, you can temporarily use the Isaac Lab version.

## RViz Instructions
1. Install ROS 2 and RViz2.  
2. In the `HA4_URDF_XML` folder, run:  

```bash
colcon build
source install/setup.bash
ros2 launch left_sharpa_ha4 display.launch.py  # View left hand URDF in RViz
ros2 launch right_sharpa_ha4 display.launch.py # View right hand URDF in RViz
```


