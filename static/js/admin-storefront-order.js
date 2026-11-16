(() => {
  "use strict";

  const grid = document.getElementById("storefrontOrderGrid");
  const form = document.getElementById("storefrontOrderForm");
  const output = document.getElementById("orderedProductIds");
  if (!grid || !form || !output) return;

  const status = document.getElementById("storefrontOrderStatus");
  const photoSummary = document.getElementById("storefrontPhotoSummary");
  const cards = () => Array.from(grid.querySelectorAll(":scope > .storefront-order-card"));
  const hasImage = card => card.dataset.hasImage === "1";
  const originalOrder = cards().slice();
  let photoFirstMode = false;

  const sync = () => {
    const current = cards();
    output.value = JSON.stringify(current.map(card => card.dataset.productId));
    const photoCount = current.filter(hasImage).length;
    const noPhotoCount = current.length - photoCount;
    if (photoSummary) {
      photoSummary.textContent = `${photoCount.toLocaleString()} products with photos · ${noPhotoCount.toLocaleString()} without photos · No-photo section starts at position ${(photoCount + 1).toLocaleString()}`;
    }
  };

  const announce = message => {
    if (status) status.textContent = message;
  };

  const placeCards = list => {
    const fragment = document.createDocumentFragment();
    list.forEach(card => fragment.appendChild(card));
    grid.appendChild(fragment);
    sync();
  };

  const sortPhotosFirst = () => {
    photoFirstMode = true;
    const current = cards();
    const withPhotos = current.filter(hasImage);
    const withoutPhotos = current.filter(card => !hasImage(card));
    placeCards([...withPhotos, ...withoutPhotos]);
    announce(`Done. ${withPhotos.length.toLocaleString()} products with photos are first. Products without photos now begin at position ${(withPhotos.length + 1).toLocaleString()}. Save display order to publish this arrangement.`);
  };

  const resetOrder = () => {
    photoFirstMode = false;
    placeCards(originalOrder.slice());
    announce("Unsaved changes have been undone. The editor is back to the order it had when this page opened.");
  };

  const move = (card, direction) => {
    if (!card) return;
    if (direction === "up" && card.previousElementSibling) {
      grid.insertBefore(card, card.previousElementSibling);
    } else if (direction === "down" && card.nextElementSibling) {
      grid.insertBefore(card.nextElementSibling, card);
    }
    sync();
  };

  grid.addEventListener("click", event => {
    const button = event.target.closest("button[data-move]");
    if (!button) return;
    move(button.closest(".storefront-order-card"), button.dataset.move);
  });

  document.querySelector("[data-sort-photos-first]")?.addEventListener("click", sortPhotosFirst);
  document.querySelector("[data-reset-storefront-order]")?.addEventListener("click", resetOrder);

  let dragged = null;
  let pointerId = null;
  let captureElement = null;
  let moved = false;
  let startX = 0;
  let startY = 0;
  let lastX = 0;
  let lastY = 0;
  let autoScrollFrame = 0;

  const stopAutoScroll = () => {
    if (autoScrollFrame) cancelAnimationFrame(autoScrollFrame);
    autoScrollFrame = 0;
  };

  const autoScroll = () => {
    if (!dragged) return stopAutoScroll();
    const edge = 76;
    const viewportHeight = window.innerHeight || document.documentElement.clientHeight;
    if (lastY < edge) {
      const speed = Math.max(7, Math.round((edge - lastY) / 4));
      window.scrollBy(0, -speed);
    } else if (lastY > viewportHeight - edge) {
      const speed = Math.max(7, Math.round((lastY - (viewportHeight - edge)) / 4));
      window.scrollBy(0, speed);
    }
    // Re-evaluate the item beneath a stationary pointer while the page scrolls.
    insertAtPointer(lastX, lastY);
    autoScrollFrame = requestAnimationFrame(autoScroll);
  };

  const startAutoScroll = () => {
    if (!autoScrollFrame) autoScrollFrame = requestAnimationFrame(autoScroll);
  };

  const insertAtPointer = (x, y) => {
    const previousPointerEvents = dragged.style.pointerEvents;
    dragged.style.pointerEvents = "none";
    const target = document.elementFromPoint(x, y)?.closest(".storefront-order-card");
    dragged.style.pointerEvents = previousPointerEvents;
    if (!target || target === dragged || !grid.contains(target)) return;

    const rect = target.getBoundingClientRect();
    const sameRow = y >= rect.top && y <= rect.bottom;
    const insertAfter = sameRow
      ? x > rect.left + rect.width / 2
      : y > rect.top + rect.height / 2;
    const reference = insertAfter ? target.nextElementSibling : target;
    if (reference !== dragged) grid.insertBefore(dragged, reference);
    cards().forEach(card => card.classList.toggle("is-over", card === target));
  };

  const finishDrag = () => {
    if (!dragged) return;
    dragged.classList.remove("is-dragging");
    cards().forEach(card => card.classList.remove("is-over"));
    try {
      if (captureElement && pointerId !== null && captureElement.hasPointerCapture?.(pointerId)) {
        captureElement.releasePointerCapture(pointerId);
      }
    } catch (_) { /* Pointer may already have been released by the browser. */ }
    stopAutoScroll();
    dragged = null;
    pointerId = null;
    captureElement = null;
    moved = false;
    sync();
  };

  grid.addEventListener("pointerdown", event => {
    if (event.button !== 0 || dragged) return;
    const card = event.target.closest(".storefront-order-card");
    if (!card) return;

    const handle = event.target.closest(".storefront-drag-handle");
    const interactive = event.target.closest("a, button, input, select, textarea");
    // Touch starts from the grip so normal swipes on product cards still scroll.
    // With a mouse, the product card itself is a convenient drag surface.
    if (event.pointerType === "touch" && !handle) return;
    if (event.pointerType !== "touch" && !handle && interactive) return;

    dragged = card;
    pointerId = event.pointerId;
    captureElement = event.target;
    startX = lastX = event.clientX;
    startY = lastY = event.clientY;
    moved = false;
    try { captureElement.setPointerCapture?.(pointerId); } catch (_) { /* Continue with document listeners. */ }
    if (handle) event.preventDefault();
  });

  document.addEventListener("pointermove", event => {
    if (!dragged || event.pointerId !== pointerId) return;
    lastX = event.clientX;
    lastY = event.clientY;
    if (!moved && Math.hypot(lastX - startX, lastY - startY) < 6) return;
    moved = true;
    dragged.classList.add("is-dragging");
    insertAtPointer(lastX, lastY);
    startAutoScroll();
  });

  document.addEventListener("pointerup", event => {
    if (dragged && event.pointerId === pointerId) finishDrag();
  });
  document.addEventListener("pointercancel", event => {
    if (dragged && event.pointerId === pointerId) finishDrag();
  });
  window.addEventListener("blur", finishDrag);

  grid.addEventListener("keydown", event => {
    if (!event.target.matches(".storefront-drag-handle")) return;
    if (event.key === "ArrowUp" || event.key === "ArrowDown") {
      event.preventDefault();
      move(event.target.closest(".storefront-order-card"), event.key === "ArrowUp" ? "up" : "down");
    }
  });

  // A remote image can fail after the page is rendered. Count it as unavailable
  // so the next photo-first run puts it in the no-photo section.
  grid.addEventListener("error", event => {
    const image = event.target;
    if (!(image instanceof HTMLImageElement) || !image.closest(".storefront-order-card")) return;
    const card = image.closest(".storefront-order-card");
    card.dataset.hasImage = "0";
    image.replaceWith(Object.assign(document.createElement("div"), {
      className: "storefront-order-no-image",
      textContent: "Photo unavailable"
    }));
    if (photoFirstMode) {
      const current = cards();
      placeCards([...current.filter(hasImage), ...current.filter(card => !hasImage(card))]);
    } else {
      sync();
    }
  }, true);

  form.addEventListener("submit", sync);
  sync();
})();
