(() => {
  "use strict";
  const grid = document.getElementById("storefrontOrderGrid");
  const form = document.getElementById("storefrontOrderForm");
  const output = document.getElementById("orderedProductIds");
  if (!grid || !form || !output) return;

  const cards = () => Array.from(grid.querySelectorAll(":scope > .storefront-order-card"));
  const sync = () => { output.value = JSON.stringify(cards().map(card => card.dataset.productId)); };
  const move = (card, direction) => {
    if (!card) return;
    if (direction === "up" && card.previousElementSibling) grid.insertBefore(card, card.previousElementSibling);
    if (direction === "down" && card.nextElementSibling) grid.insertBefore(card.nextElementSibling, card);
    sync();
  };
  grid.addEventListener("click", event => {
    const button = event.target.closest("button[data-move]");
    if (!button) return;
    move(button.closest(".storefront-order-card"), button.dataset.move);
  });

  let dragged = null;
  let pointerId = null;
  let moved = false;
  let startX = 0;
  let startY = 0;
  const clearDrag = () => {
    if (dragged) dragged.classList.remove("is-dragging");
    cards().forEach(card => card.classList.remove("is-over"));
    dragged = null; pointerId = null; moved = false;
    sync();
  };
  const insertAtPointer = (x, y) => {
    const target = document.elementFromPoint(x, y)?.closest(".storefront-order-card");
    if (!target || target === dragged || !grid.contains(target)) return;
    const rect = target.getBoundingClientRect();
    const after = (y > rect.top + rect.height / 2) ||
      (Math.abs(y - (rect.top + rect.height / 2)) < rect.height / 2 && x > rect.left + rect.width / 2);
    grid.insertBefore(dragged, after ? target.nextElementSibling : target);
  };
  grid.addEventListener("pointerdown", event => {
    const handle = event.target.closest(".storefront-drag-handle");
    if (!handle || event.button !== 0) return;
    dragged = handle.closest(".storefront-order-card");
    if (!dragged) return;
    pointerId = event.pointerId; startX = event.clientX; startY = event.clientY; moved = false;
    event.preventDefault();
  });
  document.addEventListener("pointermove", event => {
    if (!dragged || event.pointerId !== pointerId) return;
    if (!moved && Math.hypot(event.clientX - startX, event.clientY - startY) < 5) return;
    moved = true; dragged.classList.add("is-dragging");
    // Keep the dragged card out of hit-testing so the card underneath is discoverable.
    dragged.style.pointerEvents = "none";
    insertAtPointer(event.clientX, event.clientY);
    dragged.style.pointerEvents = "";
  });
  document.addEventListener("pointerup", event => {
    if (!dragged || event.pointerId !== pointerId) return;
    clearDrag();
  });
  document.addEventListener("pointercancel", event => {
    if (dragged && event.pointerId === pointerId) clearDrag();
  });
  grid.addEventListener("keydown", event => {
    if (!event.target.matches(".storefront-drag-handle")) return;
    if (event.key === "ArrowUp" || event.key === "ArrowDown") {
      event.preventDefault();
      move(event.target.closest(".storefront-order-card"), event.key === "ArrowUp" ? "up" : "down");
    }
  });
  form.addEventListener("submit", sync);
  sync();
})();
