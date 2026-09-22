"""Product image helpers using exact real-product URLs only.

The public storefront never creates or displays generated product artwork. Known
products use curated direct image URLs; administrator-uploaded data URLs remain
supported. Unknown products intentionally show a neutral unavailable-image state.
"""

import base64


REAL_PRODUCT_IMAGES = {
    'Axe Dark Temptation 150ml': 'https://images.openbeautyfacts.org/images/products/871/764/425/6183/front_fr.17.400.jpg',
    'Axe Deodorant Spray 100ml': 'https://images.openbeautyfacts.org/images/products/000/009/613/2289/front_fr.19.400.jpg',
    'Axe Deodorant Spray 150ml': 'https://images.openbeautyfacts.org/images/products/871/256/124/9638/front_fr.26.400.jpg',
    'Bananas 1kg': 'https://cdn.mafrservices.com/sys-master-root/h2f/h59/16871973060638/1362_main.jpg?im=Resize%3D376',
    'Cooking Bananas 1kg': 'https://cdn.mafrservices.com/sys-master-root/h3a/hdb/16871974797342/1367_main.jpg?im=Resize%3D480',
    'Fresh Produce Potatoes 1kg': 'https://cdn.mafrservices.com/pim-content/KEN/media/product/14767/1775746800/14767_main.jpg?im=Resize%3D376',
    'Fresh Eggs Tray 30 Pack': 'https://cdn.mafrservices.com/sys-master-root/h7d/hbd/50866627182622/194745_main.jpg?im=Resize%3D480',
    'Fresh Eggs 15 Pack': 'https://cdn.mafrservices.com/sys-master-root/hb1/ha7/52644035985438/8034_main.jpg',
    'Potatoes 1kg': 'https://cdn.mafrservices.com/pim-content/KEN/media/product/14767/1775746800/14767_main.jpg?im=Resize%3D376',
    'Brookside Fresh Milk 1L': 'https://cdn.mafrservices.com/sys-master-root/h26/h03/16975375761438/43317_main.jpg?im=Resize%3D480',
    'Brookside Fresh Milk 250ml': 'https://cdnprod.mafretailproxy.com/sys-master-root/h36/h14/16975813509150/43316_main.jpg_480Wx480H',
    'Brookside Fresh Milk 2L': 'https://cdnprod.mafretailproxy.com/sys-master-root/h36/h14/16975813509150/43316_main.jpg_480Wx480H',
    'Brookside Fresh Milk 500ml': 'https://cdn.mafrservices.com/pim-content/KEN/media/product/43276/1742392804/43276_main.jpg',
    'Brookside Natural Yoghurt 500ml': 'https://cdn.mafrservices.com/pim-content/KEN/media/product/44082/1742392804/44082_main.jpg?im=Resize%3D480',
    'Brookside Vanilla Yoghurt 500ml': 'https://cdn.mafrservices.com/sys-master-root/h78/h60/12456806842398/47410_Main.jpg?im=Resize%3D480',
    'Brookside Yoghurt Strawberry 500ml': 'https://cdn.mafrservices.com/pim-content/KEN/media/product/43324/1742392804/43324_main.jpg',
    'KCC Yoghurt 500ml': 'https://cdn.mafrservices.com/sys-master-root/ha7/h9a/17328239214622/11686_main.jpg',
    'Cadbury Dairy Milk 180g': 'https://images.openfoodfacts.org/images/products/930/061/707/5462/front_en.10.400.jpg',
    'Chupa Chups Lollipops 10s': 'https://images.openfoodfacts.org/images/products/841/003/112/2510/front_fr.3.400.jpg',
    'Coca-Cola 1.25L': 'https://media.edgexm.co.ke/photos/products/Coca_Cola_Coke_Pet_Bottle_500ml.jpg',
    'Coca-Cola 2L': 'https://images.openfoodfacts.org/images/products/750/105/530/2925/front_es.27.400.jpg',
    'Coca-Cola 300ml': 'https://media.edgexm.co.ke/photos/products/Coca_Cola_Coke_Pet_Bottle_500ml.jpg',
    'Coca-Cola 500ml': 'https://images.openfoodfacts.org/images/products/008/800/911/0616/front_fr.7.400.jpg',
    'Coca-Cola Soft Drink 1.25L': 'https://media.edgexm.co.ke/photos/products/Coca_Cola_Coke_Pet_Bottle_500ml.jpg',
    'Coca-Cola Soft Drink 2L': 'https://media.edgexm.co.ke/photos/products/Coca_Cola_Coke_Pet_Bottle_500ml.jpg',
    'Coca-Cola Soft Drink 300ml': 'https://media.edgexm.co.ke/photos/products/Coca_Cola_Coke_Pet_Bottle_500ml.jpg',
    'Coca-Cola Soft Drink 500ml': 'https://media.edgexm.co.ke/photos/products/Coca_Cola_Coke_Pet_Bottle_500ml.jpg',
    'Colgate Charcoal Gentle 140g': 'https://cdn.mafrservices.com/pim-content/KEN/media/product/222023/1742392804/222023_main.jpg',
    'Colgate Charcoal Gentle 35g': 'https://cdn.mafrservices.com/pim-content/KEN/media/product/222023/1742392804/222023_main.jpg',
    'Colgate Charcoal Gentle 70g': 'https://cdn.mafrservices.com/pim-content/KEN/media/product/222023/1742392804/222023_main.jpg',
    'Colgate Herbal With Salt 140g': 'https://cdn.mafrservices.com/pim-content/KEN/media/product/222023/1742392804/222023_main.jpg',
    'Colgate Herbal With Salt 70g': 'https://cdn.mafrservices.com/pim-content/KEN/media/product/222023/1742392804/222023_main.jpg',
    'Colgate Maximum Cavity Protection 100ml': 'https://cdn.mafrservices.com/pim-content/KEN/media/product/222023/1742392804/222023_main.jpg',
    'Colgate Maximum Cavity Protection 140ml': 'https://cdn.mafrservices.com/pim-content/KEN/media/product/222023/1742392804/222023_main.jpg',
    'Colgate Maximum Cavity Protection 35ml': 'https://cdn.mafrservices.com/pim-content/KEN/media/product/222023/1742392804/222023_main.jpg',
    'Colgate Maximum Cavity Protection 70ml': 'https://cdn.mafrservices.com/pim-content/KEN/media/product/222023/1742392804/222023_main.jpg',
    'Colgate Triple Action 100ml': 'https://cdn.mafrservices.com/pim-content/KEN/media/product/222023/1742392804/222023_main.jpg',
    'Corn Flakes 250g': 'https://images.openfoodfacts.org/images/products/294/849/600/8583/front_en.3.400.jpg',
    'Daawat Basmati Rice 1kg': 'https://images.openfoodfacts.org/images/products/890/153/707/1018/front_fr.6.400.jpg',
    'Daima Fresh Milk 1L': 'https://www.beibora.co.ke/asset/products/section_d/Daima%20Uht%20Fino%20Bora%20500%20Ml.jpg',
    'Daima Fresh Milk 250ml': 'https://www.beibora.co.ke/asset/products/section_d/Daima%20Uht%20Fino%20Bora%20500%20Ml.jpg',
    'Daima Fresh Milk 2L': 'https://www.beibora.co.ke/asset/products/section_d/Daima%20Uht%20Fino%20Bora%20500%20Ml.jpg',
    'Daima Fresh Milk 500ml': 'https://www.beibora.co.ke/asset/products/section_d/Daima%20Uht%20Fino%20Bora%20500%20Ml.jpg',
    'Daima UHT Fino Bora 1L': 'https://www.beibora.co.ke/asset/products/section_d/Daima%20Uht%20Fino%20Bora%20500%20Ml.jpg',
    'Daima UHT Fino Bora 500ml': 'https://www.beibora.co.ke/asset/products/section_d/Daima%20Uht%20Fino%20Bora%20500%20Ml.jpg',
    'Daima UHT Milk Fino 1L': 'https://www.beibora.co.ke/asset/products/section_d/Daima%20Uht%20Fino%20Bora%20500%20Ml.jpg',
    'Daima UHT Milk Fino 200ml': 'https://www.beibora.co.ke/asset/products/section_d/Daima%20Uht%20Fino%20Bora%20500%20Ml.jpg',
    'Daima UHT Milk Fino 500ml': 'https://cdn.mafrservices.com/sys-master-root/h0f/h7f/27062187524126/16012_main.jpg?im=Resize%3D376',
    'Del Monte Mango Juice 1L': 'https://cdn.mafrservices.com/pim-content/KEN/media/product/38611/1742392804/38611_main.jpg',
    'Del Monte Mango Juice 2L': 'https://kayshia.com/cdn/shop/products/20220905_231415_1500x.jpg?v=1662522855',
    'Del Monte Mango Juice 3L': 'https://kayshia.com/cdn/shop/products/20220905_231415_1500x.jpg?v=1662522855',
    'Del Monte Orange Juice 1L': 'https://kayshia.com/cdn/shop/products/20220905_231415_1500x.jpg?v=1662522855',
    'Del Monte Orange Juice 2L': 'https://kayshia.com/cdn/shop/products/20220905_231415_1500x.jpg?v=1662522855',
    'Del Monte Orange Juice 3L': 'https://kayshia.com/cdn/shop/products/20220905_231415_1500x.jpg?v=1662522855',
    'Del Monte Tropical Juice 1L': 'https://kayshia.com/cdn/shop/products/20220905_231415_1500x.jpg?v=1662522855',
    'Delamere Strawberry Yoghurt 150ml': 'https://cdn.mafrservices.com/sys-master-root/h69/h56/26449306615838/67552_main.jpg?im=Resize%3D376',
    'Delamere Strawberry Yoghurt 250ml': 'https://cdn.mafrservices.com/sys-master-root/h69/h56/26449306615838/67552_main.jpg?im=Resize%3D376',
    'Delamere Strawberry Yoghurt 500ml': 'https://cdn.mafrservices.com/pim-content/KEN/media/product/44079/1742392804/44079_main.jpg',
    'Fanta Orange 1.25L': 'https://images.openfoodfacts.org/images/products/930/067/500/3094/front_en.21.400.jpg',
    'Fanta Orange 300ml': 'https://images.openfoodfacts.org/images/products/890/176/402/1251/front_en.16.400.jpg',
    'Fanta Orange 500ml': 'https://images.openfoodfacts.org/images/products/500/011/264/4869/front_en.3.400.jpg',
    'Fresha Fresh Milk 1L': 'https://www.beibora.co.ke/asset/products/section_d/Fresha%20Aseptic%20500Ml%20Pouch18%20Pcs.jpg',
    'Fresha Fresh Milk 250ml': 'https://www.beibora.co.ke/asset/products/section_d/Fresha%20Aseptic%20500Ml%20Pouch18%20Pcs.jpg',
    'Fresha Fresh Milk 2L': 'https://www.beibora.co.ke/asset/products/section_d/Fresha%20Aseptic%20500Ml%20Pouch18%20Pcs.jpg',
    'Fresha Fresh Milk 500ml': 'https://www.beibora.co.ke/asset/products/section_d/Fresha%20Aseptic%20500Ml%20Pouch18%20Pcs.jpg',
    'Fresha Strawberry Yoghurt 150ml': 'https://www.beibora.co.ke/asset/products/section_d/Fresha%20Aseptic%20500Ml%20Pouch18%20Pcs.jpg',
    'Fresha Strawberry Yoghurt 250ml': 'https://www.beibora.co.ke/asset/products/section_d/Fresha%20Aseptic%20500Ml%20Pouch18%20Pcs.jpg',
    'Fresha Strawberry Yoghurt 500ml': 'https://www.beibora.co.ke/asset/products/section_d/Fresha%20Aseptic%20500Ml%20Pouch18%20Pcs.jpg',
    'Golden Fry Cooking Oil 1L': 'https://shop.bidcoafrica.com/cdn/shop/files/Golden-Fry-1L.jpg?v=1737536953&width=1946',
    'Golden Fry Cooking Oil 2L': 'https://cdnprod.mafretailproxy.com/sys-master-root/h38/h04/12462424457246/34101_Main.jpg_480Wx480H',
    'Golden Fry Cooking Oil 3L': 'https://shop.bidcoafrica.com/cdn/shop/files/Golden-Fry-1L.jpg?v=1737536953&width=1946',
    'Golden Fry Cooking Oil 5L': 'https://shop.bidcoafrica.com/cdn/shop/files/Golden-Fry-5L_5c79bf31-1072-4346-9c05-90833df2cad7.jpg?v=1737536953&width=1946',
    'Head & Shoulders 180ml': 'https://images.openbeautyfacts.org/images/products/750/043/502/0077/front_en.3.400.jpg',
    'Ilara Fresh Milk 1L': 'https://www.beibora.co.ke/asset/products/section_d/Ilara%20Fresh%20Milk%20500Ml-Pouch.jpg',
    'Ilara Fresh Milk 250ml': 'https://www.beibora.co.ke/asset/products/section_d/Ilara%20Fresh%20Milk%20500Ml-Pouch.jpg',
    'Ilara Fresh Milk 2L': 'https://www.beibora.co.ke/asset/products/section_d/Ilara%20Fresh%20Milk%20500Ml-Pouch.jpg',
    'Ilara Fresh Milk 500ml': 'https://www.beibora.co.ke/asset/products/section_d/Ilara%20Fresh%20Milk%20500Ml-Pouch.jpg',
    'Instant Noodles Beef 5 Pack': 'https://images.openfoodfacts.org/images/products/008/968/617/0085/front_en.40.400.jpg',
    "Johnson's Baby Oil 200ml": 'https://cdn.mafrservices.com/pim-content/KEN/media/product/9802/1724850003/9802_main.jpg?im=Resize%3D376',
    'KCC Fresh Milk 1L': 'https://cdn.mafrservices.com/sys-master-root/hc1/h82/12452122132510/11666_Main.jpg?im=Resize%3D480',
    'KCC Fresh Milk 250ml': 'https://cdn.mafrservices.com/sys-master-root/hc1/h82/12452122132510/11666_Main.jpg?im=Resize%3D480',
    'KCC Fresh Milk 2L': 'https://cdn.mafrservices.com/sys-master-root/hc1/h82/12452122132510/11666_Main.jpg?im=Resize%3D480',
    'KCC Fresh Milk 500ml': 'https://cdn.mafrservices.com/sys-master-root/hc1/h82/12452122132510/11666_Main.jpg?im=Resize%3D480',
    "Kellogg's Corn Flakes 250g": 'https://images.openfoodfacts.org/images/products/294/849/600/8583/front_en.3.400.jpg',
    'Kericho Gold Loose Leaf Tea 100g': 'https://cdn.mafrservices.com/pim-content/QAT/media/product/1060856/1749999603/1060856_main.jpg',
    'Kericho Gold Loose Leaf Tea 250g': 'https://cdn.mafrservices.com/pim-content/QAT/media/product/1060856/1749999603/1060856_main.jpg',
    'Kericho Gold Loose Leaf Tea 500g': 'https://cdn.mafrservices.com/pim-content/QAT/media/product/1060856/1749999603/1060856_main.jpg',
    'Kericho Gold Tea Bags 100s': 'https://owinosupermarket.com/cdn/shop/files/rn-image_picker_lib_temp_d2b467a9-75d4-433d-99b6-2b86d6b6807f.jpg?v=1779035646&width=720',
    'Kericho Gold Tea Bags 25s': 'https://cdn.mafrservices.com/pim-content/QAT/media/product/1060856/1749999603/1060856_main.jpg',
    'Kericho Gold Tea Bags 50s': 'https://cdn.mafrservices.com/pim-content/QAT/media/product/1060856/1749999603/1060856_main.jpg',
    'Listerine Mouthwash 250ml': 'https://images.openbeautyfacts.org/images/products/357/466/127/6496/front_en.8.400.jpg',
    'Monster Energy Drink 500ml': 'https://images.openfoodfacts.org/images/products/506/016/669/4531/front_fr.20.400.jpg',
    'Nescafe Classic 50g': 'https://images.openfoodfacts.org/images/products/761/303/191/8737/front_en.3.400.jpg',
    'Nescafe Classic Instant Coffee 100g': 'https://images.openfoodfacts.org/images/products/761/303/191/8867/front_fr.3.400.jpg',
    'Nescafe Gold 100g': 'https://images.openfoodfacts.org/images/products/761/303/366/4199/front_el.3.400.jpg',
    'Nestle KitKat 4 Finger': 'https://images.openfoodfacts.org/images/products/629/400/353/2987/front_en.31.400.jpg',
    'Nestle Milo 400g': 'https://images.openfoodfacts.org/images/products/603/300/008/9595/front_en.5.400.jpg',
    'Nivea Body Lotion 400ml': 'https://images.openbeautyfacts.org/images/products/400/580/823/7487/front_en.9.400.jpg',
    'Omo Detergent 1kg': 'https://cdn.mafrservices.com/sys-master-root/h05/h10/62003535642654/14163_main.jpg?im=Resize%3D480',
    'Omo Detergent 2kg': 'https://cdn.mafrservices.com/sys-master-root/h05/h10/62003535642654/14163_main.jpg?im=Resize%3D480',
    'Omo Detergent 3kg': 'https://cdn.mafrservices.com/sys-master-root/h05/h10/62003535642654/14163_main.jpg?im=Resize%3D480',
    'Omo Detergent 500g': 'https://cdn.mafrservices.com/sys-master-root/h05/h10/62003535642654/14163_main.jpg?im=Resize%3D480',
    'Pearl Pishori Rice 1kg': 'https://cdn.mafrservices.com/pim-content/KEN/media/product/31962/1720080003/31962_main.jpg?im=Resize%3D480',
    'Pearl Pishori Rice 2kg': 'https://cdn.mafrservices.com/pim-content/KEN/media/product/31962/1720080003/31962_main.jpg?im=Resize%3D480',
    'Pearl Pishori Rice 5kg': 'https://cdn.mafrservices.com/pim-content/KEN/media/product/31962/1720080003/31962_main.jpg?im=Resize%3D480',
    'Penne Pasta 500g': 'https://images.openfoodfacts.org/images/products/800/374/012/0313/front_en.21.400.jpg',
    'Red Bull Energy Drink 473ml': 'https://images.openfoodfacts.org/images/products/900/249/021/4951/front_fr.40.400.jpg',
    'Rexona Men 50ml': 'https://images.openbeautyfacts.org/images/products/000/009/609/7335/front_fr.12.400.jpg',
    'Rexona Women 50ml': 'https://images.openbeautyfacts.org/images/products/000/009/611/3318/front_fr.5.400.jpg',
    'Rina Cooking Oil 1L': 'https://cdn.mafrservices.com/pim-content/KEN/media/product/21018/1742392804/21018_main.jpg',
    'Rina Cooking Oil 2L': 'https://cdn.mafrservices.com/pim-content/KEN/media/product/21019/1779091205/21019_main.jpg?im=Resize%3D376',
    'Rina Cooking Oil 3L': 'https://cdn.mafrservices.com/pim-content/KEN/media/product/21018/1742392804/21018_main.jpg',
    'Rina Cooking Oil 500ml': 'https://cdn.mafrservices.com/pim-content/KEN/media/product/21018/1742392804/21018_main.jpg',
    'Rina Cooking Oil 5L': 'https://cdn.mafrservices.com/pim-content/KEN/media/product/21018/1742392804/21018_main.jpg',
    'Sprite 1.25L': 'https://images.openfoodfacts.org/images/products/955/558/921/4955/front_en.5.400.jpg',
    'Sprite 500ml': 'https://images.openfoodfacts.org/images/products/000/005/449/1069/front_en.293.400.jpg',
    'Supa Loaf Brown Bread 400g': 'https://cdn.mafrservices.com/sys-master-root/h45/h99/12681201647646/74581_main.jpg?im=Resize%3D376',
    'Supa Loaf Brown Bread 600g': 'https://cdn.mafrservices.com/sys-master-root/h02/ha0/12681201451038/82689_main.jpg?im=Resize%3D376',
    'Supa Loaf Brown Bread 800g': 'https://cdn.mafrservices.com/sys-master-root/h02/ha0/12681201451038/82689_main.jpg?im=Resize%3D376',
    'Supa Loaf White Bread 400g': 'https://cdn.mafrservices.com/sys-master-root/h86/h95/12681201778718/74580_main.jpg?im=Resize%3D376',
    'Supa Loaf White Bread 600g': 'https://cdn.mafrservices.com/sys-master-root/h02/ha0/12681201451038/82689_main.jpg?im=Resize%3D376',
    'Supa Loaf White Bread 800g': 'https://cdn.mafrservices.com/sys-master-root/h02/ha0/12681201451038/82689_main.jpg?im=Resize%3D376',
    'Superloaf Brown Bread 400g': 'https://cdn.mafrservices.com/sys-master-root/hb4/h24/12681202991134/82690_main.jpg?im=Resize%3D376',
    'Superloaf Brown Bread 600g': 'https://cdn.mafrservices.com/sys-master-root/hb4/h24/12681202991134/82690_main.jpg?im=Resize%3D376',
    'Superloaf Brown Bread 800g': 'https://cdn.mafrservices.com/sys-master-root/hb4/h24/12681202991134/82690_main.jpg?im=Resize%3D376',
    'Superloaf Premium Brown Bread 600g': 'https://cdn.mafrservices.com/sys-master-root/hb4/h24/12681202991134/82690_main.jpg?im=Resize%3D376',
    'Superloaf Premium White Bread 600g': 'https://cdn.mafrservices.com/sys-master-root/hb4/h24/12681202991134/82690_main.jpg?im=Resize%3D376',
    'Superloaf White Bread 400g': 'https://cdn.mafrservices.com/sys-master-root/hb4/h24/12681202991134/82690_main.jpg?im=Resize%3D376',
    'Superloaf White Bread 600g': 'https://cdn.mafrservices.com/sys-master-root/hb4/h24/12681202991134/82690_main.jpg?im=Resize%3D376',
    'Superloaf White Bread 800g': 'https://cdn.mafrservices.com/sys-master-root/hb4/h24/12681202991134/82690_main.jpg?im=Resize%3D376',
    'Tresemme Shampoo 400ml': 'https://images.openbeautyfacts.org/images/products/789/115/003/3580/front_en.6.400.jpg',
    'Tropical Heat Chilli Lemon Crisps 100g': 'https://cdn.mafrservices.com/pim-content/KEN/media/product/32275/1742392804/32275_main.jpg',
    'Tropical Heat Chilli Lemon Crisps 200g': 'https://cdn.mafrservices.com/pim-content/KEN/media/product/32275/1742392804/32275_main.jpg',
    'Tropical Heat Chilli Lemon Crisps 50g': 'https://cdn.mafrservices.com/pim-content/KEN/media/product/32275/1742392804/32275_main.jpg',
    'Tropical Heat Potato Crisps 100g': 'https://cdn.mafrservices.com/pim-content/KEN/media/product/32275/1742392804/32275_main.jpg',
    'Tropical Heat Potato Crisps 200g': 'https://cdn.mafrservices.com/pim-content/KEN/media/product/32275/1742392804/32275_main.jpg',
    'Tropical Heat Potato Crisps 50g': 'https://cdn.mafrservices.com/pim-content/KEN/media/product/32275/1742392804/32275_main.jpg',
    'Unga Exe All Purpose Flour 2kg': 'https://artcaffemarket.co.ke/cdn/shop/files/11428-262795.jpg?v=1734955008',
}

_NORMALIZED_REAL_IMAGES = {" ".join(k.split()).casefold(): v for k, v in REAL_PRODUCT_IMAGES.items()}

def normalize_product_name(value: str) -> str:
    return " ".join(str(value or "").split()).strip().casefold()


def real_product_image_url(name: str) -> str:
    """Return the curated direct photo URL for an exact known product name."""
    return _NORMALIZED_REAL_IMAGES.get(normalize_product_name(name), "")


def is_data_image_url(url: str) -> bool:
    raw = str(url or "").strip().lower()
    return raw.startswith("data:image/") and "," in raw


def public_product_image(product) -> str:
    """Return only a trusted exact match or an administrator-uploaded image.

    Unknown remote URLs are intentionally ignored so the storefront cannot show a
    stale or unverified image.
    """
    exact = real_product_image_url(getattr(product, "name", ""))
    if exact:
        return exact
    raw = str(getattr(product, "image_url", "") or "").strip()
    if is_data_image_url(raw):
        return raw
    return ""


def has_public_product_image(product) -> bool:
    return bool(public_product_image(product))


def image_is_real(product) -> bool:
    return has_public_product_image(product)



def data_url_to_bytes(url: str):
    raw = str(url or "").strip()
    if not is_data_image_url(raw):
        return None
    header, encoded = raw.split(",", 1)
    try:
        binary = base64.b64decode(encoded)
    except Exception:
        return None
    mime = header.split(";", 1)[0].replace("data:", "").strip().lower() or "image/png"
    return binary, mime
