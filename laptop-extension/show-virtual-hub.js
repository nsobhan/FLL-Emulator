// Lets the SPIKE web app list a virtual hub in its Bluetooth picker.
// The app only shows devices that advertise the hub service *and* LEGO
// manufacturer data. A Mac can't advertise manufacturer data, so this adds a
// second filter that matches the hub service alone. Real hubs still match the
// original filters, so they keep showing up as usual.
(() => {
  const HUB_SERVICE = "0000fd02-0000-1000-8000-00805f9b34fb";
  const proto = window.Bluetooth && Bluetooth.prototype;
  if (!proto || proto.__virtualHubPatched) return;
  const original = proto.requestDevice;
  proto.requestDevice = function (options) {
    try {
      const filters = (options && options.filters) || [];
      const wantsHub = filters.some(f => (f.services || []).some(s => String(s).toLowerCase() === HUB_SERVICE));
      const hasPlain = filters.some(f => !f.manufacturerData && !f.namePrefix && !f.name &&
        (f.services || []).some(s => String(s).toLowerCase() === HUB_SERVICE));
      if (wantsHub && !hasPlain) {
        options = Object.assign({}, options, { filters: filters.concat([{ services: [HUB_SERVICE] }]) });
        console.info("[virtual hub] Bluetooth picker will also list hubs without LEGO manufacturer data");
      }
    } catch (e) {
      console.warn("[virtual hub] left the Bluetooth filter unchanged:", e);
    }
    return original.call(this, options);
  };
  proto.__virtualHubPatched = true;
})();
