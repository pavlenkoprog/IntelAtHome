export function cameraZoom(viewer) {
  const height = viewer.camera.positionCartographic.height;
  return Math.max(0, Math.min(22, Math.log2(35_200_000 / Math.max(height, 1))));
}

export function viewBBox(viewer) {
  const Cesium = window.Cesium;
  const zoom = String(Math.round(cameraZoom(viewer)));
  const rect = viewer.camera.computeViewRectangle(viewer.scene.globe.ellipsoid);
  if (!rect) {
    return { south: "-70", west: "-180", north: "70", east: "180", zoom };
  }
  return {
    south: String(Cesium.Math.toDegrees(rect.south)),
    west: String(Cesium.Math.toDegrees(rect.west)),
    north: String(Cesium.Math.toDegrees(rect.north)),
    east: String(Cesium.Math.toDegrees(rect.east)),
    zoom,
  };
}

export function pickLatLng(viewer, windowPosition, onSurface = false) {
  const Cesium = window.Cesium;
  let cartesian = null;
  if (onSurface) {
    const ray = viewer.camera.getPickRay(windowPosition);
    cartesian = ray && viewer.scene.globe.pick(ray, viewer.scene);
  }
  if (!cartesian) {
    cartesian = viewer.camera.pickEllipsoid(windowPosition, viewer.scene.globe.ellipsoid);
  }
  if (!cartesian) {
    return null;
  }
  const carto = Cesium.Cartographic.fromCartesian(cartesian);
  return {
    lat: Cesium.Math.toDegrees(carto.latitude),
    lon: Cesium.Math.toDegrees(carto.longitude),
  };
}

export function globeHomeView() {
  const Cesium = window.Cesium;
  return {
    destination: Cesium.Cartesian3.fromDegrees(30, 25, 18_000_000),
    orientation: {
      heading: 0,
      pitch: Cesium.Math.toRadians(-90),
      roll: 0,
    },
  };
}
