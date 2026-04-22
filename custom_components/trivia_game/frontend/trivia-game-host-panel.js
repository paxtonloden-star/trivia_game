class TriviaGameHostPanel extends HTMLElement {
  static get properties() {
    return {
      hass: { type: Object },
      narrow: { type: Boolean },
      route: { type: Object },
      panel: { type: Object },
    };
  }

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._initialized = false;
  }

  connectedCallback() {
    this.render();
  }

  set hass(value) {
    this._hass = value;
    if (!this._initialized) {
      this.render();
    }
  }

  get hass() {
    return this._hass;
  }

  render() {
    if (!this.shadowRoot || this._initialized) return;
    const path = "/api/trivia_game/static/host.html";
    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          height: 100%;
        }
        .wrap {
          position: fixed;
          inset: 0;
          background: var(--primary-background-color);
        }
        iframe {
          width: 100%;
          height: 100%;
          border: 0;
          background: transparent;
        }
      </style>
      <div class="wrap">
        <iframe src="${path}" title="Trivia Game Host"></iframe>
      </div>
    `;
    this._initialized = true;
  }
}

customElements.define("trivia-game-host-panel", TriviaGameHostPanel);
