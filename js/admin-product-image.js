(() => {
  "use strict";
  const form = document.getElementById("productEditForm");
  const input = document.getElementById("productImageInput");
  const preview = document.getElementById("productImagePreview");
  const empty = document.getElementById("productImageEmpty");
  const status = document.getElementById("productImageStatus");
  const remove = document.getElementById("removeProductImage");
  if (!form || !input || !preview || !empty || !status) return;

  const savedImageSrc = preview.getAttribute("src") || "";
  const savedImageVisible = !preview.hidden && Boolean(savedImageSrc);
  let temporaryPreviewUrl = null;
  const clearTemporaryUrl = () => {
    if (temporaryPreviewUrl) {
      URL.revokeObjectURL(temporaryPreviewUrl);
      temporaryPreviewUrl = null;
    }
  };

  input.addEventListener("change", () => {
    const file = input.files && input.files[0];
    if (!file) return;
    if (!file.type || !file.type.startsWith("image/")) {
      input.value = "";
      status.textContent = "Please choose a valid image file.";
      return;
    }
    if (file.size > 8 * 1024 * 1024) {
      input.value = "";
      status.textContent = "That photo is larger than 8 MB. Choose a smaller image.";
      return;
    }
    clearTemporaryUrl();
    temporaryPreviewUrl = URL.createObjectURL(file);
    preview.src = temporaryPreviewUrl;
    preview.hidden = false;
    empty.hidden = true;
    if (remove) remove.checked = false;
    status.textContent = `${file.name} — preview only; press Save product to store it.`;
  });

  if (remove) {
    remove.addEventListener("change", () => {
      if (remove.checked) {
        input.value = "";
        clearTemporaryUrl();
        preview.hidden = true;
        empty.hidden = false;
        status.textContent = "The current photo will be removed when you save.";
      } else if (savedImageVisible) {
        preview.src = savedImageSrc;
        preview.hidden = false;
        empty.hidden = true;
        status.textContent = "Current saved product photo";
      } else {
        preview.hidden = true;
        empty.hidden = false;
        status.textContent = "Choose a photo to preview it here";
      }
    });
  }
  form.addEventListener("submit", clearTemporaryUrl);
})();
