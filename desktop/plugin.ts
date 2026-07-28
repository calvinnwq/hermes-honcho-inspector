export const PLUGIN_ID = "honcho-inspector"
export const PLUGIN_VERSION = "0.1.0"

const plugin = {
  id: PLUGIN_ID,
  name: "Honcho Inspector",
  defaultEnabled: false,
  register() {
    // Slice 0 proves the install and release contract without product behavior.
  }
}

export default plugin
