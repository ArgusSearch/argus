// The bulk of the layer, loaded as its own chunk while the loader shows (StyleProvider), so it is never part of
// the page without the flag and lands after styles.css and views.css in the cascade.
import "./fx.css";
import "./workspace/workspace.css";
import "./workspace/pages.css";
