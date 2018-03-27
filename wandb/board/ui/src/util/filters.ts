export function greeter(person: string) {
    return 'Hello, ' + person;
}

export function greetany(person: any) {
    return 'Hello, ' + person;
}

export function greetShawn() {
    return greeter('shawn');
}

interface KeyVal {
    [key: string]: number | string;
}

interface Run {
    name: string;
    config: KeyVal;
    summary: KeyVal;
}

// filter has a filter method, which takes a list of runs and returns runs
interface Filter {
    match(runs: Run): boolean;
}

class RunKey {
    static fromString(keyString: string) {
        let [section, name] = keyString.split(':');
        if (!name) {
            name = section;
            section = 'run';
        }
        return new RunKey(section, name);
    }

    constructor(public section: string, public key: string) {}
}

class EqualityFilter implements Filter {
    constructor(public key: string, public value: string) {

    }

    match(run: Run) {
        return (run.config[this.key] === this.value);
    }
}