import "@fontsource/ibm-plex-mono/latin-400.css";
import "@fontsource/ibm-plex-mono/latin-500.css";
import "@fontsource/ibm-plex-sans/latin-400.css";
import "@fontsource/ibm-plex-sans/latin-500.css";
import "@fontsource/ibm-plex-sans/latin-600.css";
import "@fontsource/saira-condensed/latin-600.css";
import "@fontsource/saira-condensed/latin-700.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import ImportAssemblyApp from "./ImportAssemblyApp";
import "./styles.css";
import "./import-assembly.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ImportAssemblyApp />
  </StrictMode>,
);
