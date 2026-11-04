import rat from "../assets/zodiac/rat.png";
import ox from "../assets/zodiac/ox.png";
import tiger from "../assets/zodiac/tiger.png";
import rabbit from "../assets/zodiac/rabbit.png";
import dragon from "../assets/zodiac/dragon.png";
import snake from "../assets/zodiac/snake.png";
import horse from "../assets/zodiac/horse.png";
import goat from "../assets/zodiac/goat.png";
import monkey from "../assets/zodiac/monkey.png";
import rooster from "../assets/zodiac/rooster.png";
import dog from "../assets/zodiac/dog.png";
import pig from "../assets/zodiac/pig.png";

const ZODIAC = [
  { name: "鼠", image: rat },
  { name: "牛", image: ox },
  { name: "虎", image: tiger },
  { name: "兔", image: rabbit },
  { name: "龙", image: dragon },
  { name: "蛇", image: snake },
  { name: "马", image: horse },
  { name: "羊", image: goat },
  { name: "猴", image: monkey },
  { name: "鸡", image: rooster },
  { name: "狗", image: dog },
  { name: "猪", image: pig },
];

// Reviews already carry the zodiac from their associated report.
export function zodiacForName(name: string) {
  return ZODIAC.find(zodiac => zodiac.name === name);
}

// Match the lunar birth year shown in basic information, not the Gregorian year.
export function zodiacForLunarYear(year: number) {
  return ZODIAC[((year - 4) % 12 + 12) % 12];
}
