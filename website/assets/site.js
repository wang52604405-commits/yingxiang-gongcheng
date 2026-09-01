(function () {
  "use strict";

  var nav = document.querySelector(".site-nav");
  var toggle = document.querySelector(".nav-toggle");
  var links = document.querySelector(".nav-links");

  function closeMenu() {
    if (!nav || !toggle) return;
    nav.classList.remove("menu-open");
    toggle.setAttribute("aria-expanded", "false");
  }

  if (toggle && nav) {
    toggle.addEventListener("click", function () {
      var open = nav.classList.toggle("menu-open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
    if (links) links.addEventListener("click", function (event) {
      if (event.target.closest("a")) closeMenu();
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") closeMenu();
    });
  }

  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var revealItems = Array.prototype.slice.call(document.querySelectorAll("[data-reveal]"));
  if (reduceMotion || !("IntersectionObserver" in window)) {
    revealItems.forEach(function (item) { item.classList.add("is-visible"); });
  } else {
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("is-visible");
        observer.unobserve(entry.target);
      });
    }, { rootMargin: "0px 0px -8%", threshold: 0.08 });
    revealItems.forEach(function (item) { observer.observe(item); });
  }

  var lightbox = document.getElementById("lightbox");
  var lightboxImage = document.getElementById("lightboxImage");
  var lightboxTitle = document.getElementById("lightboxTitle");
  var previewButtons = Array.prototype.slice.call(document.querySelectorAll("[data-preview-image]"));

  function closeLightbox() {
    if (!lightbox) return;
    lightbox.classList.remove("is-open");
    lightbox.setAttribute("aria-hidden", "true");
    document.body.classList.remove("no-scroll");
  }

  function openLightbox(button) {
    if (!lightbox || !lightboxImage) return;
    lightboxImage.src = button.getAttribute("data-preview-image") || "";
    lightboxImage.alt = button.getAttribute("data-preview-title") || "产品界面预览";
    if (lightboxTitle) lightboxTitle.textContent = lightboxImage.alt;
    lightbox.classList.add("is-open");
    lightbox.setAttribute("aria-hidden", "false");
    document.body.classList.add("no-scroll");
    lightbox.querySelector("[data-lightbox-close]")?.focus();
  }

  previewButtons.forEach(function (button) {
    button.addEventListener("click", function () { openLightbox(button); });
  });
  if (lightbox) {
    lightbox.querySelectorAll("[data-lightbox-close]").forEach(function (button) {
      button.addEventListener("click", closeLightbox);
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && lightbox.classList.contains("is-open")) closeLightbox();
    });
  }
})();
