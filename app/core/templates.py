# Nepali and Roman Nepali strings must be reviewed by a native speaker before any real pilot.
"""All reply strings (en / rn / ne) and the helpers that assemble them into <= 2 SMS segments.
Writing rules: plain everyday words, one line per idea, a word first and at most one number for a change,
numbered options one per line. Lists ending in _opts are menu options, in order."""
from __future__ import annotations

from datetime import date

from app.core import aliases
from app.core.sms import Part, fit_parts, menu_part

TEMPLATES = {
    "en": {
        "welcome": "Agahi: Kalimati market prices and weather by SMS.\nReply 1 to start.\nNE = Nepali, RN = Roman Nepali",
        "loc_q": "Where are you?", "not_sure": "Not sure", "more": "More",
        "loc_saved": "Location saved: {loc}", "loc_default": "Location set to whole area.\nChange it with 6.",
        "main_opts": ["Price", "Forecast", "Weather", "Sell or keep", "Arrivals", "Location", "Language"],
        "pick_crop": "Which crop?", "menu": "Menu",
        "pick_h": "{crop}: price in how long?",
        "h_opts": ["7 days", "14 days", "21 days", "28 days", "1 month", "2 months", "3 months"],
        "weather_menu": "Weather for {loc}", "wmenu_opts": ["Next 7 days", "Weeks 2 to 4", "Next 3 months"],
        "lang_menu": "Language", "lang_opts": ["English", "Roman Nepali", "Nepali"], "lang_set": "Language: English",
        "price_head": "{crop}{variant}", "price": "Rs{p} per kg {when}", "today": "today", "on": "on {d}",
        "ch_up": "Higher than last price ({pct}%)", "ch_down": "Lower than last price ({pct}%)", "ch_same": "Same as last price",
        "no_new": "No new price {when}.\nLast price: Rs{p} per kg on {d}",
        "price_opts": ["Forecast", "Weather", "Arrivals", "Other crop"],
        "fc_head": "{crop} price in {h}", "fc_range": "Likely Rs{lo} to Rs{hi} per kg",
        "fc_up": "Likely higher than today ({pct}%)", "fc_down": "Likely lower than today ({pct}%)",
        "fc_same": "Likely about the same as today", "fc_now": "Today: Rs{p0}",
        "st_reliable": "Rough estimate.", "st_indicative": "Rough estimate.",
        "st_seasonal": "Rough estimate from past seasons.",
        "pattern": "Likely Rs{lo} to Rs{hi} per kg\nRough estimate from past years.",
        "unavailable": "No estimate for this yet.", "not_trained": "Estimate is not ready yet.",
        "no_price": "{crop}\nNo price data.", "fc_opts": ["Other time", "Other crop", "Sell or keep"],
        "w_live": "Tomorrow in {loc}: about {mm}mm rain (estimated)", "w_live_dry": "Tomorrow in {loc}: no rain (estimated)",
        "w_clim_wet": "Rain likely now in {loc} (estimated)", "w_clim_some": "Some rain now in {loc} (estimated)",
        "w_clim_dry": "Mostly dry now in {loc} (estimated)",
        "w7_head": "{loc}, next 7 days (estimated)", "w7_tot": "Rain: {tot}mm in total", "w7_most": "Most rain: {day} ({mm}mm)",
        "w7_temp": "Daytime {lo} to {hi}C",
        "w7c_head": "{loc}, next 7 days (estimated)\nUsual for this time:", "w7c_rain": "{word}, about {tot}mm",
        "w7c_temp": "Daytime about {lo} to {hi}C",
        "rain_most": "Rain on most days", "rain_some": "Rain on some days", "rain_dry": "Mostly dry",
        "past_years": "Estimated from past years.", "nocoord": "(Past data only)",
        "w_opts": ["Weeks 2 to 4", "Next 3 months"],
        "w24_head": "{loc}, weeks 2 to 4 (estimated)", "w24_clim": "Usually {desc}: {lo} to {hi}mm a week",
        "w24_model": "Rain about {a}mm, {b}mm, {c}mm a week", "st_rough": "Rough estimate.",
        "dry": "dry", "moderate": "some rain", "wet": "wet",
        "m13_head": "{loc}, next 30 days (estimated)", "m13_mid": "Usual rain: about {mid}mm", "m13_last": "Last 30 days: {word}",
        "an_more": "more rain than usual", "an_less": "less rain than usual", "an_same": "about usual rain",
        "adv_head": "{crop}: {action}", "SELL_NOW": "sell now", "HOLD": "keep 1 to 2 days", "WAIT": "wait 1 to 2 days",
        "conf_low": "Rough estimate, just a tip.", "conf_medium": "Rough estimate.",
        "r_fc_up": "Price may go up in {h} ({pct}%).", "r_fc_down": "Price may go down in {h} ({pct}%).",
        "r_fc_flat": "Price likely about the same.", "r_rain": "Heavy rain tomorrow in {loc} ({mm}mm). Hard to pick and carry.",
        "r_up": "Price went up this week ({pct}%).", "r_down": "Price went down this week ({pct}%).",
        "r_flat": "Price steady this week.", "r_nofc": "Based on this week's prices.",
        "qty": "{q}kg is about Rs{v} today.", "adv_opts": ["Forecast", "Weather"],
        "arr_head": "{crop} arrivals", "arr_val": "{t} tonnes {when}",
        "arr_more": "More than usual ({pct}%)", "arr_less": "Less than usual ({pct}%)", "arr_same": "About normal",
        "arr_none": "No arrivals data.", "arr_opts": ["Price", "Other crop"],
        "cmp_head": "Prices on {d}", "help": "Agahi help\nSend a crop name for its price: tomato\nAdd days for a forecast: tomato 14 days\nSend rain for weather\n0 Menu. STOP stops alerts.",
        "stop": "Agahi alerts stopped.\nYou can still ask any time.\nSend START to turn them on.",
        "start": "Agahi alerts are on again.", "hello": "Namaste!", "clarify": "Did you mean:",
        "unknown": "Sorry, I did not understand.", "rate": "Agahi: too many messages. Please try again later.",
        "invalid": "Please send one of the numbers.", "asof": "(Data from {d})", "sample": "[SAMPLE]",
        "intent_PRICE": "Price of {crop}", "intent_FORECAST": "Forecast for {crop}", "intent_ADVICE": "Sell or keep {crop}",
        "intent_ARRIVALS": "Arrivals of {crop}", "intent_COMPARE": "Compare {crop}",
        "intent_PRICE0": "Price", "intent_FORECAST0": "Forecast", "intent_ADVICE0": "Sell or keep",
        "intent_ARRIVALS0": "Arrivals", "intent_COMPARE0": "Compare prices", "intent_WEATHER": "Weather",
        "intent_HELP": "Help", "intent_LOCATION": "Change location", "intent_LANG": "Change language", "intent_MENU": "Menu",
        "al_price_up": "Agahi alert: {crop} price went up ({pct}%).\nNow Rs{p} per kg ({d}).\nSTOP to stop alerts.",
        "al_price_down": "Agahi alert: {crop} price went down ({pct}%).\nNow Rs{p} per kg ({d}).\nSTOP to stop alerts.",
        "al_rain": "Agahi alert: heavy rain tomorrow in {loc} ({mm}mm).\nPlan picking and transport.\nSTOP to stop alerts.",
        "al_fc": "Agahi alert: {crop} price may change in 7 days ({pct}%).\nLikely Rs{lo} to Rs{hi}. Rough estimate.\nSTOP to stop alerts.",
        "days": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
    },
    "rn": {
        "welcome": "Agahi: Kalimati bazar ko bhau ra mausam SMS ma.\nSuru garna 1 pathaunus.\nEN = English, NE = Nepali",
        "loc_q": "Tapai kahan hunuhunchha?", "not_sure": "Thaha chhaina", "more": "Aru",
        "loc_saved": "Thau rakhiyo: {loc}", "loc_default": "Thau: sabai kshetra.\n6 thichera badalnus.",
        "main_opts": ["Bhau", "Bhau anuman", "Mausam", "Bechne/rakhne", "Aagaman", "Thau", "Bhasha"],
        "pick_crop": "Kun bali?", "menu": "Menu",
        "pick_h": "{crop}: kati din pachhi ko bhau?",
        "h_opts": ["7 din", "14 din", "21 din", "28 din", "1 mahina", "2 mahina", "3 mahina"],
        "weather_menu": "Mausam: {loc}", "wmenu_opts": ["Aaglo 7 din", "Hapta 2 dekhi 4", "Aaglo 3 mahina"],
        "lang_menu": "Bhasha", "lang_opts": ["English", "Roman Nepali", "Nepali"], "lang_set": "Bhasha: Roman Nepali",
        "price_head": "{crop}{variant}", "price": "{when} Rs{p} prati kg", "today": "Aaja", "on": "{d} ma",
        "ch_up": "Aghillo bhanda mahango ({pct}%)", "ch_down": "Aghillo bhanda sasto ({pct}%)", "ch_same": "Aghillo jastai",
        "no_new": "{when} naya bhau aayena.\nAntim bhau: Rs{p} prati kg ({d})",
        "price_opts": ["Bhau anuman", "Mausam", "Aagaman", "Arko bali"],
        "fc_head": "{crop}: {h} pachhi ko bhau", "fc_range": "Sambhavit Rs{lo} dekhi Rs{hi} prati kg",
        "fc_up": "Aaja bhanda badhna sakchha ({pct}%)", "fc_down": "Aaja bhanda ghatna sakchha ({pct}%)",
        "fc_same": "Aaja jastai rahana sakchha", "fc_now": "Aaja: Rs{p0}",
        "st_reliable": "Moto anuman.", "st_indicative": "Moto anuman.",
        "st_seasonal": "Pahile ka sijan herera moto anuman.",
        "pattern": "Sambhavit Rs{lo} dekhi Rs{hi} prati kg\nPahile ka barsa herera moto anuman.",
        "unavailable": "Ahile yasko anuman chhaina.", "not_trained": "Anuman ahile tayar chhaina.",
        "no_price": "{crop}\nBhau ko data chhaina.", "fc_opts": ["Arko samay", "Arko bali", "Bechne/rakhne"],
        "w_live": "Bholi {loc} ma: lagbhag {mm}mm paani (anuman)", "w_live_dry": "Bholi {loc} ma: paani pardaina (anuman)",
        "w_clim_wet": "Yo bela {loc} ma paani parna sakchha (anuman)", "w_clim_some": "Yo bela {loc} ma kehi paani (anuman)",
        "w_clim_dry": "Yo bela {loc} prayah sukkha (anuman)",
        "w7_head": "{loc}, aaglo 7 din (anuman)", "w7_tot": "Paani: jamma {tot}mm", "w7_most": "Dherai paani: {day} ({mm}mm)",
        "w7_temp": "Din ko tapkram {lo} dekhi {hi}C",
        "w7c_head": "{loc}, aaglo 7 din (anuman)\nYo bela prayah:", "w7c_rain": "{word}, lagbhag {tot}mm",
        "w7c_temp": "Din ko tapkram lagbhag {lo} dekhi {hi}C",
        "rain_most": "Dherai din paani", "rain_some": "Kehi din paani", "rain_dry": "Prayah sukkha",
        "past_years": "Pahile ka barsa herera anuman.", "nocoord": "(Purano data matra)",
        "w_opts": ["Hapta 2 dekhi 4", "Aaglo 3 mahina"],
        "w24_head": "{loc}, hapta 2 dekhi 4 (anuman)", "w24_clim": "Prayah {desc}: hapta ma {lo} dekhi {hi}mm",
        "w24_model": "Paani lagbhag {a}, {b}, {c}mm prati hapta", "st_rough": "Moto anuman.",
        "dry": "sukkha", "moderate": "kehi paani", "wet": "dherai paani",
        "m13_head": "{loc}, aaglo 30 din (anuman)", "m13_mid": "Prayah paani: lagbhag {mid}mm", "m13_last": "Pachhillo 30 din: {word}",
        "an_more": "sadharan bhanda dherai paani", "an_less": "sadharan bhanda kam paani", "an_same": "sadharan jastai",
        "adv_head": "{crop}: {action}", "SELL_NOW": "aaja bechnus", "HOLD": "1-2 din rakhnus", "WAIT": "1-2 din parkhanus",
        "conf_low": "Moto anuman, salah matra.", "conf_medium": "Moto anuman.",
        "r_fc_up": "{h} ma bhau badhna sakchha ({pct}%).", "r_fc_down": "{h} ma bhau ghatna sakchha ({pct}%).",
        "r_fc_flat": "Bhau uhi rahana sakchha.", "r_rain": "Bholi {loc} ma thulo paani ({mm}mm). Tipna ra lana garo.",
        "r_up": "Yo hapta bhau badhyo ({pct}%).", "r_down": "Yo hapta bhau ghatyo ({pct}%).",
        "r_flat": "Yo hapta bhau sthir.", "r_nofc": "Yo hapta ko bhau herera.",
        "qty": "{q}kg ko aaja lagbhag Rs{v}.", "adv_opts": ["Bhau anuman", "Mausam"],
        "arr_head": "{crop} aagaman", "arr_val": "{when} {t} ton",
        "arr_more": "Sadharan bhanda dherai ({pct}%)", "arr_less": "Sadharan bhanda kam ({pct}%)", "arr_same": "Sadharan jastai",
        "arr_none": "Aagaman ko data chhaina.", "arr_opts": ["Bhau", "Arko bali"],
        "cmp_head": "{d} ko bhau", "help": "Agahi sahayog\nBhau: bali ko naam pathaunus (golbheda)\nAnuman: golbheda 14 din\nMausam: paani\n0 Menu. STOP le alert banda.",
        "stop": "Agahi alert banda bhayo.\nJaba pani sodhna saknuhunchha.\nPheri chahiye START pathaunus.",
        "start": "Agahi alert pheri suru bhayo.", "hello": "Namaste!", "clarify": "Tapai ko matlab:",
        "unknown": "Maaf garnus, bujhina.", "rate": "Agahi: dherai SMS aayo. Pachhi pathaunus.",
        "invalid": "Kripaya number pathaunus.", "asof": "({d} ko data)", "sample": "[SAMPLE]",
        "intent_PRICE": "{crop} ko bhau", "intent_FORECAST": "{crop} ko bhau anuman", "intent_ADVICE": "{crop} bechne/rakhne",
        "intent_ARRIVALS": "{crop} aagaman", "intent_COMPARE": "{crop} tulana",
        "intent_PRICE0": "Bhau", "intent_FORECAST0": "Bhau anuman", "intent_ADVICE0": "Bechne/rakhne",
        "intent_ARRIVALS0": "Aagaman", "intent_COMPARE0": "Bhau tulana", "intent_WEATHER": "Mausam",
        "intent_HELP": "Sahayog", "intent_LOCATION": "Thau badalne", "intent_LANG": "Bhasha badalne", "intent_MENU": "Menu",
        "al_price_up": "Agahi suchana: {crop} ko bhau badhyo ({pct}%).\nAhile Rs{p} prati kg ({d}).\nSTOP le banda.",
        "al_price_down": "Agahi suchana: {crop} ko bhau ghatyo ({pct}%).\nAhile Rs{p} prati kg ({d}).\nSTOP le banda.",
        "al_rain": "Agahi suchana: bholi {loc} ma thulo paani ({mm}mm).\nTipne ra dhuwani milaunus.\nSTOP le banda.",
        "al_fc": "Agahi suchana: 7 din ma {crop} ko bhau pharak huna sakchha ({pct}%).\nRs{lo} dekhi Rs{hi}, moto anuman.\nSTOP le banda.",
        "days": ["Som", "Mangal", "Budha", "Bihi", "Shukra", "Shani", "Aaita"],
    },
    "ne": {
        "welcome": "Agahi: कालीमाटीको भाउ र मौसम SMS मा।\nसुरु गर्न 1 पठाउनुहोस्।\nEN = English, RN = Roman",
        "loc_q": "तपाईं कहाँ हुनुहुन्छ?", "not_sure": "थाहा छैन", "more": "अरू",
        "loc_saved": "ठाउँ राखियो: {loc}", "loc_default": "ठाउँ: सबै क्षेत्र।\n6 ले बदल्नुहोस्।",
        "main_opts": ["भाउ", "भाउ अनुमान", "मौसम", "बेच्ने/राख्ने", "आगमन", "ठाउँ", "भाषा"],
        "pick_crop": "कुन बाली?", "menu": "मेनु",
        "pick_h": "{crop}: कति दिनपछिको भाउ?",
        "h_opts": ["7 दिन", "14 दिन", "21 दिन", "28 दिन", "1 महिना", "2 महिना", "3 महिना"],
        "weather_menu": "मौसम: {loc}", "wmenu_opts": ["अर्को 7 दिन", "हप्ता 2 देखि 4", "अर्को 3 महिना"],
        "lang_menu": "भाषा", "lang_opts": ["English", "Roman Nepali", "नेपाली"], "lang_set": "भाषा: नेपाली",
        "price_head": "{crop}{variant}", "price": "{when} रु{p} प्रति केजी", "today": "आज", "on": "{d}",
        "ch_up": "अघिल्लोभन्दा महँगो ({pct}%)", "ch_down": "अघिल्लोभन्दा सस्तो ({pct}%)", "ch_same": "अघिल्लो जस्तै",
        "no_new": "{when} नयाँ भाउ आएन।\nअन्तिम भाउ: रु{p} ({d})",
        "price_opts": ["भाउ अनुमान", "मौसम", "आगमन", "अर्को बाली"],
        "fc_head": "{crop}: {h}पछिको भाउ", "fc_range": "सम्भावित रु{lo} देखि रु{hi}",
        "fc_up": "आजभन्दा बढ्न सक्छ ({pct}%)", "fc_down": "आजभन्दा घट्न सक्छ ({pct}%)",
        "fc_same": "आज जस्तै रहन सक्छ", "fc_now": "आज: रु{p0}",
        "st_reliable": "मोटो अनुमान।", "st_indicative": "मोटो अनुमान।",
        "st_seasonal": "पहिलेका सिजन हेरेर मोटो अनुमान।",
        "pattern": "सम्भावित रु{lo} देखि रु{hi}\nपहिलेका वर्ष हेरेर मोटो अनुमान।",
        "unavailable": "अहिले यसको अनुमान छैन।", "not_trained": "अनुमान अहिले तयार छैन।",
        "no_price": "{crop}\nभाउ छैन।", "fc_opts": ["अर्को समय", "अर्को बाली", "बेच्ने/राख्ने"],
        "w_live": "भोलि {loc}मा: करिब {mm}mm वर्षा (अनुमान)", "w_live_dry": "भोलि {loc}मा: वर्षा छैन (अनुमान)",
        "w_clim_wet": "यो बेला {loc}मा वर्षा हुन सक्छ (अनुमान)", "w_clim_some": "यो बेला {loc}मा केही वर्षा (अनुमान)",
        "w_clim_dry": "यो बेला {loc} प्रायः सुख्खा (अनुमान)",
        "w7_head": "{loc}, अर्को 7 दिन (अनुमान)", "w7_tot": "वर्षा: जम्मा {tot}mm", "w7_most": "धेरै वर्षा: {day} ({mm}mm)",
        "w7_temp": "दिनको तापक्रम {lo} देखि {hi}C",
        "w7c_head": "{loc}, अर्को 7 दिन (अनुमान)\nयो बेला प्रायः:", "w7c_rain": "{word}, करिब {tot}mm",
        "w7c_temp": "दिनको तापक्रम करिब {lo} देखि {hi}C",
        "rain_most": "धेरै दिन वर्षा", "rain_some": "केही दिन वर्षा", "rain_dry": "प्रायः सुख्खा",
        "past_years": "पहिलेका वर्ष हेरेर अनुमान।", "nocoord": "(पुरानो डाटा मात्र)",
        "w_opts": ["हप्ता 2 देखि 4", "अर्को 3 महिना"],
        "w24_head": "{loc}, हप्ता 2 देखि 4 (अनुमान)", "w24_clim": "प्रायः {desc}: हप्तामा {lo} देखि {hi}mm",
        "w24_model": "वर्षा करिब {a}, {b}, {c}mm प्रति हप्ता", "st_rough": "मोटो अनुमान।",
        "dry": "सुख्खा", "moderate": "केही वर्षा", "wet": "धेरै वर्षा",
        "m13_head": "{loc}, अर्को 30 दिन (अनुमान)", "m13_mid": "प्रायः वर्षा: करिब {mid}mm", "m13_last": "गत 30 दिन: {word}",
        "an_more": "सामान्यभन्दा बढी वर्षा", "an_less": "सामान्यभन्दा कम वर्षा", "an_same": "सामान्य जस्तै",
        "adv_head": "{crop}: {action}", "SELL_NOW": "आज बेच्नुहोस्", "HOLD": "1-2 दिन राख्नुहोस्", "WAIT": "1-2 दिन पर्खनुहोस्",
        "conf_low": "मोटो अनुमान।", "conf_medium": "मोटो अनुमान।",
        "r_fc_up": "{h}मा भाउ बढ्न सक्छ ({pct}%)।", "r_fc_down": "{h}मा भाउ घट्न सक्छ ({pct}%)।",
        "r_fc_flat": "भाउ उस्तै रहन सक्छ।", "r_rain": "भोलि {loc}मा ठूलो वर्षा ({mm}mm), ढुवानी गाह्रो।",
        "r_up": "यो हप्ता भाउ बढ्यो ({pct}%)।", "r_down": "यो हप्ता भाउ घट्यो ({pct}%)।",
        "r_flat": "यो हप्ता भाउ स्थिर।", "r_nofc": "यो हप्ताको भाउ हेरेर।",
        "qty": "{q} केजीको आज करिब रु{v}।", "adv_opts": ["भाउ अनुमान", "मौसम"],
        "arr_head": "{crop} आगमन", "arr_val": "{when} {t} टन",
        "arr_more": "सामान्यभन्दा बढी ({pct}%)", "arr_less": "सामान्यभन्दा कम ({pct}%)", "arr_same": "सामान्य जस्तै",
        "arr_none": "आगमनको डाटा छैन।", "arr_opts": ["भाउ", "अर्को बाली"],
        "cmp_head": "{d} को भाउ", "help": "Agahi सहायता\nभाउ: बालीको नाम (गोलभेडा)\nअनुमान: गोलभेडा 14 दिन\nमौसम: वर्षा\n0 मेनु। STOP ले बन्द।",
        "stop": "Agahi सूचना बन्द भयो।\nजहिले पनि सोध्न सक्नुहुन्छ।\nफेरि चाहियो भने START पठाउनुहोस्।",
        "start": "Agahi सूचना फेरि सुरु भयो।", "hello": "नमस्ते!", "clarify": "तपाईंको मतलब:",
        "unknown": "माफ गर्नुहोस्, बुझिएन।", "rate": "Agahi: धेरै SMS आयो। पछि पठाउनुहोस्।",
        "invalid": "कृपया नम्बर पठाउनुहोस्।", "asof": "({d} को डाटा)", "sample": "[SAMPLE]",
        "intent_PRICE": "{crop} भाउ", "intent_FORECAST": "{crop} भाउ अनुमान", "intent_ADVICE": "{crop} बेच्ने/राख्ने",
        "intent_ARRIVALS": "{crop} आगमन", "intent_COMPARE": "{crop} तुलना",
        "intent_PRICE0": "भाउ", "intent_FORECAST0": "भाउ अनुमान", "intent_ADVICE0": "बेच्ने/राख्ने",
        "intent_ARRIVALS0": "आगमन", "intent_COMPARE0": "भाउ तुलना", "intent_WEATHER": "मौसम",
        "intent_HELP": "सहायता", "intent_LOCATION": "ठाउँ बदल्ने", "intent_LANG": "भाषा बदल्ने", "intent_MENU": "मेनु",
        "al_price_up": "Agahi सूचना: {crop}को भाउ बढ्यो ({pct}%)।\nअहिले रु{p} ({d})।\nSTOP ले बन्द।",
        "al_price_down": "Agahi सूचना: {crop}को भाउ घट्यो ({pct}%)।\nअहिले रु{p} ({d})।\nSTOP ले बन्द।",
        "al_rain": "Agahi सूचना: भोलि {loc}मा ठूलो वर्षा ({mm}mm)।\nSTOP ले बन्द।",
        "al_fc": "Agahi सूचना: 7 दिनमा {crop}को भाउ फरक हुन सक्छ ({pct}%)।\nरु{lo} देखि रु{hi}, मोटो अनुमान।\nSTOP ले बन्द।",
        "days": ["सोम", "मंगल", "बुध", "बिही", "शुक्र", "शनि", "आइत"],
    },
}
MONTHS = {"en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
          "ne": ["जनवरी", "फेब्रुअरी", "मार्च", "अप्रिल", "मे", "जुन", "जुलाई", "अगस्ट", "सेप्टेम्बर", "अक्टोबर", "नोभेम्बर", "डिसेम्बर"]}
VARIANT_WORDS = {
    "en": {"small": "small", "large": "large", "local": "local", "indian": "Indian", "nepali": "Nepali",
           "terai": "Terai", "tunnel": "tunnel", "hybrid": "hybrid", "chinese": "Chinese"},
    "rn": {"small": "sano", "large": "thulo", "local": "lokal", "indian": "bharatiya", "nepali": "nepali",
           "terai": "terai", "tunnel": "tunnel", "hybrid": "hybrid", "chinese": "chini"},
    "ne": {"small": "सानो", "large": "ठूलो", "local": "लोकल", "indian": "भारतीय", "nepali": "नेपाली",
           "terai": "तराई", "tunnel": "टनेल", "hybrid": "हाइब्रिड", "chinese": "चिनियाँ"},
}
SAME_CHANGE_PCT = 1.0      # price change smaller than this reads "same"
SAME_FORECAST_PCT = 3.0    # forecast change smaller than this reads "about the same"
ARRIVALS_BAND_PCT = 10.0   # arrivals within +/-10% of the 7-day average read "normal"


def t(lang: str, key: str, **kw) -> str:
    """Template lookup with formatting."""
    return TEMPLATES[lang][key].format(**kw)


def opts(lang: str, key: str, numbers: list[str] | None = None, menu: bool = True) -> list[tuple[str, str]]:
    """Numbered options from a list template, plus '0 Menu' at the end when menu is True."""
    labels = TEMPLATES[lang][key]
    nums = numbers or [str(i + 1) for i in range(len(labels))]
    out = list(zip(nums, labels))
    if menu:
        out.append(("0", TEMPLATES[lang]["menu"]))
    return out


def menu(lang: str, key: str, numbers: list[str] | None = None, priority: int = 5, required: bool = False,
         extra: list[tuple[str, str]] | None = None, with_menu: bool = True) -> Part:
    """A menu Part (one option per line, shorter layouts as fallbacks)."""
    items = opts(lang, key, numbers, menu=False) + (extra or [])
    if with_menu:
        items.append(("0", TEMPLATES[lang]["menu"]))
    return menu_part(items, priority, key, required)


def to_lang_digits(text: str, lang: str) -> str:
    """Devanagari digits for ne."""
    return text.translate(aliases.TO_NE) if lang == "ne" else text


def fmt_date(d: str | date, lang: str) -> str:
    """'2026-10-03' -> '3 Oct' / '३ अक्टोबर'."""
    dd = date.fromisoformat(str(d)[:10]) if not isinstance(d, date) else d
    if lang == "ne":
        return f"{dd.day} {MONTHS['ne'][dd.month - 1]}"
    return f"{dd.day} {MONTHS['en'][dd.month - 1]}"


def signed(v: float, digits: int = 0) -> str:
    """+5 / -3 / 0."""
    r = round(v, digits) if digits else int(round(v))
    return f"+{r}" if r > 0 else f"{r}"


def money(v: float) -> str:
    """Whole rupees with thousands separators."""
    return f"{int(round(v)):,}"


def variant_label(origin: str, size: str, lang: str) -> str:
    """' (small, local)' style label from origin/size."""
    words = VARIANT_WORDS[lang]
    bits = [b for b in (words.get(size, ""), words.get(origin, "")) if b]
    return f" ({', '.join(bits)})" if bits else ""


def change_word(lang: str, pct: float, keys: tuple[str, str, str], band: float) -> str:
    """Word first, then one number: ('ch_up', 'ch_down', 'ch_same') -> 'Higher than last price (+8%)'."""
    up, down, same = keys
    if abs(pct) < band:
        return t(lang, same)
    return t(lang, up if pct > 0 else down, pct=signed(pct))


def finish(parts: list[Part], lang: str, sample: bool = False) -> tuple[str, list[str]]:
    """Add [SAMPLE] line, fit to 2 segments, convert digits for ne."""
    if sample:
        parts = [Part(t(lang, "sample"), -1, "sample", True)] + parts
    return fit_parts(parts, transform=lambda s: to_lang_digits(s, lang))
