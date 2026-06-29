(function () {
  function escapeHtml(value) {
    return String(value || "").replace(/[&<>"']/g, (character) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#039;"
    })[character]);
  }

  function renderSpotifyPanel(user, target = document.querySelector("#spotifyPanel")) {
    if (!target) return;
    const embedUrl = user?.spotifyPlaylistEmbedUrl || "";
    if (!embedUrl) {
      target.innerHTML = `
        <div class="spotify-empty">
          <strong>Trading playlist</strong>
          <p>Save a Spotify playlist on your profile to keep the same desk soundtrack here.</p>
        </div>
      `;
      return;
    }

    target.innerHTML = `
      <div class="spotify-heading">
        <span>Trading playlist</span>
        <a class="button-link" href="${escapeHtml(user.spotifyPlaylistUrl)}" target="_blank" rel="noreferrer">Open</a>
      </div>
      <iframe
        title="Connected Spotify playlist"
        src="${escapeHtml(embedUrl)}"
        height="152"
        allow="autoplay; clipboard-write; encrypted-media; fullscreen; picture-in-picture"
        loading="lazy"></iframe>
    `;
  }

  async function loadSpotifyForSession() {
    const target = document.querySelector("#spotifyPanel");
    if (!target) return;
    try {
      const response = await fetch("/api/me", { credentials: "same-origin", cache: "no-store" });
      if (!response.ok) throw new Error("No session");
      const payload = await response.json();
      renderSpotifyPanel(payload.authenticated ? payload : null, target);
    } catch {
      renderSpotifyPanel(null, target);
    }
  }

  window.MonatiseSpotify = {
    renderSpotifyPanel,
    loadSpotifyForSession
  };
})();
