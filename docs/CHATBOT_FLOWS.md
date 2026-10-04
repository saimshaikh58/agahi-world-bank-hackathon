# Chatbot flows

Any time: `STOP` (alerts off), `START` (alerts on, after sign-up), `HELP`, `MENU` or `0` (main menu after sign-up), `LANG EN|RN|NE`.
One-word shortcuts after sign-up (the simulator quick options send these; farmers can text them too): `price`/`bhau`, `forecast`/`anuman`, `weather`/`mausam`, `sell`, `arrivals`/`aagaman`. Each opens that screen.

## How a reply looks
First line: what it is about. Next lines: the value, then one plain-word line for the change. Then the numbered options, one per line. If a reply would go over 2 SMS, options are laid out two per line, then on one line, then the least important lines are dropped (options, weather line, date note).

```
Onion arrivals
85 tonnes on 2 Oct
More than usual (+17%)
1 Price
2 Other crop
0 Menu
```

## Sign-up
```
NEW --any text--> WELCOME (welcome text, sent again on every other reply)
NEW --"1"--> ASK_LOCATION (first message "1" skips the welcome)
WELCOME --"1"--> ASK_LOCATION
WELCOME --"EN"/"NE"/"RN" or "LANG xx"--> WELCOME in that language
ASK_LOCATION: "1".."6" districts from the weather file, "7" Not sure (= whole area average)
              "8" next page if more than 7 options; "0" shows the list again; a district name also works
              wrong reply -> list again; 3rd wrong reply -> Not sure saved, main menu shown
ASK_LOCATION --valid--> MAIN ("Location saved: Dhading" + main menu)
```

## Menus
```
MAIN: 1 Price  2 Forecast  3 Weather  4 Sell or keep  5 Arrivals  6 Location  9 Language
CROP LIST (shared): 7 crops per page, 8 = more, 0 = menu
PRICE    -> crop -> AFTER_PRICE    : 1 Forecast 2 Weather 3 Arrivals 4 Other crop 0 Menu
FORECAST -> crop -> PICK_HORIZON   : 1 7 days 2 14 days 3 21 days 4 28 days 5 1 month 6 2 months 7 3 months
                 -> AFTER_FORECAST : 1 Other time 2 Other crop 3 Sell or keep 0 Menu
WEATHER  -> WEATHER_MENU           : 1 Next 7 days 2 Weeks 2 to 4 3 Next 3 months
                 -> AFTER_WEATHER  : 1 Weeks 2 to 4 2 Next 3 months 0 Menu
SELL/KEEP-> crop -> AFTER_ADVICE   : 1 Forecast 2 Weather 0 Menu
ARRIVALS -> crop -> AFTER_ARRIVALS : 1 Price 2 Other crop 0 Menu
LOCATION -> district list -> saved -> MAIN
LANGUAGE -> 1 English 2 Roman Nepali 3 Nepali -> MAIN
```
A wrong number shows the current screen again (or the main menu with "Please send one of the numbers").

## Free text (after sign-up)
- `golbheda` (price), `tomato 14 din`, `alu 2 hapta`, `next hapta tamatar kasto hola` (forecast)
- `becham alu 500kg`, `alu becham ki rakhum` (sell or keep, with value for the quantity)
- `bholi paani parchha?`, `next month rain`, `weather in dhading` (weather)
- `tomato vs potato`, `indian golbheda tulana` (compare)
- `ma kavre ma chhu` (save location)
- Typos and shorthand: `golvheda`, `cauliflwr`, `kti`, `tmrw`, `dhadng` are corrected when the match is clear.

## Follow-ups (memory)
The last crop, time ahead and question are remembered:
- `and potato?` / `ani alu?`: same question for potato
- `ani?` / `and?`: next step (price, then 7-day forecast; forecast, then the next time ahead)
- `aru?` / `other?`: pick another crop for the same question
- `tyo ko 2 hapta?`: forecast in 2 weeks for the last crop
- `kati ho?`: price of the last crop

## Confidence
0.75 or more: act. Between 0.45 and 0.75: "Did you mean:" with the top two guesses as `1` and `2`, plus `0 Menu`. Below 0.45: "Sorry, I did not understand" and the main menu (logged to the Quality queue). Nothing raises.

## Wording for estimates

Every price forecast reads "rough estimate" (en), "moto anuman" (rn), "मोटो अनुमान" (ne). Cells that are not better than
the seasonal baseline read "rough estimate from past years". Every weather outlook (days 1 to 7, weeks 2 to 4, months 1 to 3)
is marked "(estimated)" / "(anuman)" / "(अनुमान)". The price range shown is the "likely range": the calibrated 50% range,
rounded to Rs5, right about half the time. The internal status (reliable, indicative, pattern only) is never shown to farmers.
Sell or keep advice also says rough estimate. Every reply stays within 2 SMS segments, with line breaks.
Nepali (ne) and Roman Nepali (rn) text still needs review by a native speaker.

Example (7 days, English):

```
Tomato price in 7 days
Likely Rs50 to Rs70 per kg
Likely about the same as today
Today: Rs55
Rough estimate.
1 Other time
2 Other crop
3 Sell or keep
0 Menu
```
