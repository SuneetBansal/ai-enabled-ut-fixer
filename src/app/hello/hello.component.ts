import { Component, signal } from "@angular/core";

@Component({
    selector: 'hello-comp',
    templateUrl: './hello.component.html',
    standalone: true
})
export class HelloComponent {
    public message = signal("This is child component")
}
