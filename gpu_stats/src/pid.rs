/// Get descendant process IDs for a given parent PID.
pub fn process_tree(parent_pid: i32) -> Result<Vec<i32>, std::io::Error> {
    match () {
        #[cfg(target_os = "linux")]
        () => {
            // Linux implementation.
            use std::collections::HashSet;
            use std::fs::read_to_string;

            let mut descendant_pids = Vec::new();
            let mut visited_pids = HashSet::new();
            let mut stack = vec![parent_pid];

            while let Some(pid) = stack.pop() {
                // Skip if we've already visited this PID
                if !visited_pids.insert(pid) {
                    continue;
                }

                let children_path = format!("/proc/{}/task/{}/children", pid, pid);
                match read_to_string(&children_path) {
                    Ok(contents) => {
                        let child_pids: Vec<i32> = contents
                            .split_whitespace()
                            .filter_map(|s| s.parse::<i32>().ok())
                            .collect();
                        stack.extend(&child_pids);
                        descendant_pids.extend(&child_pids);
                    }
                    Err(_) => {
                        continue; // Skip to the next PID
                    }
                }
            }

            Ok(descendant_pids)
        }
        #[cfg(not(target_os = "linux"))]
        () => {
            // TODO: Default case - just return the parent_pid in a vec for now
            Ok(vec![parent_pid])
        }
    }
}
