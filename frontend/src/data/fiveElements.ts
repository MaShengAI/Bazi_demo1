// Display classification only; chart facts and calculations come from the API.
const ELEMENTS = [
  { symbols: "甲乙寅卯", label: "木", className: "wood" },
  { symbols: "丙丁巳午", label: "火", className: "fire" },
  { symbols: "戊己辰戌丑未", label: "土", className: "earth" },
  { symbols: "庚辛申酉", label: "金", className: "metal" },
  { symbols: "壬癸子亥", label: "水", className: "water" },
];

export function elementForSymbol(value: string) {
  return value ? ELEMENTS.find(item => item.symbols.includes(value)) : undefined;
}
