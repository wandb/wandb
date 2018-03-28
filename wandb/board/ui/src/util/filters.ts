import {Run} from './runs';

export function greeter(person: string) {
  return 'Hello, ' + person;
}

export function greetany(person: any) {
  return 'Hello, ' + person;
}

export function greetShawn() {
  const a: any = 'asdf';
  let b = 6;
  b = a;
  return greeter('shawn');
}

// filter has a filter method, which takes a list of runs and returns runs
interface Filter {
  match(runs: Run): boolean;
}

// function makeRunKey(keyString: string): RunKey {
//   let [section, name] = keyString.split(':');
//   if (!name) {
//     name = section;
//     section = 'run';
//   }
//   return {section, name};
// }

// class EqualityFilter implements Filter {
//     constructor(public key: RunKey, public value: string) {

//     }

//     match(run: Run) {
//         return (run.config[this.key] === this.value);
//     }
// }
