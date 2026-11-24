/* Lab site helpers: click-to-play YouTube embeds. */
(function () {
  "use strict";
  document.addEventListener("click", function (ev) {
    var a = ev.target.closest ? ev.target.closest("a.yt-lite") : null;
    if (!a) return;
    var id = a.getAttribute("data-yt");
    if (!id) return;
    ev.preventDefault();
    var iframe = document.createElement("iframe");
    iframe.src = "https://www.youtube-nocookie.com/embed/" + encodeURIComponent(id) + "?autoplay=1&rel=0";
    iframe.title = a.getAttribute("title") || "YouTube video";
    iframe.allow = "accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture";
    iframe.allowFullscreen = true;
    iframe.setAttribute("referrerpolicy", "strict-origin-when-cross-origin");
    a.replaceWith(iframe);
    iframe.parentNode.classList.add("yt-lite--playing");
  });
})();
