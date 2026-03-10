import { useEffect, useRef } from "react";

const BMC_SCRIPT_SRC = "https://cdnjs.buymeacoffee.com/1.0.0/button.prod.min.js";
const BMC_PROFILE_URL = "https://buymeacoffee.com/hutchlaxgames";

export default function BuyMeCoffeeButton() {
  const mountRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;

    mount.innerHTML = "";
    const script = document.createElement("script");
    script.type = "text/javascript";
    script.src = BMC_SCRIPT_SRC;
    script.async = true;
    script.setAttribute("data-name", "bmc-button");
    script.setAttribute("data-slug", "hutchlaxgames");
    script.setAttribute("data-color", "#58879d");
    script.setAttribute("data-emoji", "");
    script.setAttribute("data-font", "Bree");
    script.setAttribute("data-text", "Buy me a coffee");
    script.setAttribute("data-outline-color", "#ffffff");
    script.setAttribute("data-font-color", "#ffffff");
    script.setAttribute("data-coffee-color", "#FFDD00");
    mount.appendChild(script);

    return () => {
      mount.innerHTML = "";
    };
  }, []);

  return (
    <div className="bmc-slot">
      <a
        className="button monetize-button"
        href={BMC_PROFILE_URL}
        target="_blank"
        rel="noopener noreferrer"
        aria-label="Support this project on Buy Me a Coffee"
      >
        Buy me a coffee
      </a>
      <div ref={mountRef} className="bmc-embed" aria-hidden="true" />
    </div>
  );
}
