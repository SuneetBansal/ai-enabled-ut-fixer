import { ComponentFixture, TestBed } from "@angular/core/testing";
import { HelloComponent } from "./hello.component";

describe('HelloComponent Test', () => {
    let fixture: ComponentFixture<HelloComponent>;
    let instance: HelloComponent;

    beforeEach(() => {
        TestBed.configureTestingModule({
        imports: [ HelloComponent ]
    }).compileComponents();
    fixture = TestBed.createComponent(HelloComponent);

    instance = fixture.componentInstance; 
    })
    
    it('should be defined', () => {
        expect(instance).toBeDefined();
    });

    it('should show correct message', () => {
        expect(instance.message()).toEqual('This is child component');
    });
    
});
