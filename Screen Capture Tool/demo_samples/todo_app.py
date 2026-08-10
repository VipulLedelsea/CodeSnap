"""A small task tracker — demo sample for Code Capture."""

from dataclasses import dataclass, field
from typing import List


@dataclass
class Task:
    title: str
    priority: int = 1
    done: bool = False


@dataclass
class Project:
    name: str
    tasks: List[Task] = field(default_factory=list)


class Tracker:
    def __init__(self):
        self.projects: List[Project] = []

    def add_project(self, name: str) -> Project:
        project = Project(name)
        self.projects.append(project)
        return project

    def add_task(self, project: Project, title: str, priority: int = 1) -> None:
        project.tasks.append(Task(title, priority))

    def complete(self, project: Project, title: str) -> bool:
        for task in project.tasks:
            if task.title == title and not task.done:
                task.done = True
                return True
        return False

    def pending(self, project: Project) -> List[Task]:
        return [t for t in project.tasks if not t.done]


def main() -> None:
    tracker = Tracker()
    work = tracker.add_project("Demo Prep")
    tracker.add_task(work, "Rehearse the script", priority=3)
    tracker.add_task(work, "Test the capture", priority=2)
    tracker.add_task(work, "Charge the laptop", priority=1)

    tracker.complete(work, "Test the capture")

    print(f"Project: {work.name}")
    for task in tracker.pending(work):
        print(f"  [P{task.priority}] {task.title}")
    print(f"{len(tracker.pending(work))} tasks left")


if __name__ == "__main__":
    main()
