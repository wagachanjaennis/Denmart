# Denmart — real product photo cache

This repository is prepared to keep catalogue photos **exactly attached to the product they belong to**.

## Folder layout

The cache uses batches of at most 100 product photos:

- `static/catalogue/products/001/` — priority ranks 1–100
- `002/` — 101–200
- `003/` — 201–300
- `004/` — 301–400
- `005/` — 401–500
- `006/`–`014/` — remaining catalogue capacity

Files are named from the unique product barcode, not a transient UUID.

## How the photos are obtained

The GitHub Action `Cache real Denmart product photos` tries, in order:

1. curated exact source attached to that SKU;
2. exact product/brand matching against the Open Food Facts family datasets;
3. exact product-page discovery on Kenyan retail sites, including Carrefour Kenya, Naivas Online, Owino Supermarket and Artcaffe Market.

Before a photo is accepted, the source is checked against the product's brand, name and pack-size identity. The same source URL and the same image bytes cannot be assigned to two different products.

## No misleading placeholders

The old generated bottle/cylinder/cartoon product visuals have been removed from the repository. A missing photo is recorded as `pending_real_photo` and the storefront shows a neutral **PHOTO NOT CACHED YET** card naming that exact product. It never substitutes a different product's photo.

## GitHub usage

Upload this project to the root of `wagachanjaennis/Denmart`, then open:

**Actions → Cache real Denmart product photos → Run workflow**

The default pass processes the first **500 priority products**. Verified photographs are written into `001`–`005` and the manifest/report is committed back to GitHub.

The Render build runs the same downloader with a 500-product limit, so the deployed site can populate its local cache even before the GitHub Action has committed all results.

## Audit trail

`static/catalogue/catalogue-image-manifest.json` records the local file, source URL, match score and source type for every cached photo. `data/github_catalogue_image_report.json` records photo/miss counts and rejected duplicate-source cases.

Product-photo serving is local-only at runtime. Customer browsing never performs a live image search.

Source image use should be checked against the source site's terms/licensing before commercial publication.
