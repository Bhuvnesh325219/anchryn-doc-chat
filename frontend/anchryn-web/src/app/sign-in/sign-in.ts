import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';

import { Auth } from '../services/auth';

@Component({
  selector: 'app-sign-in',
  imports: [FormsModule],
  templateUrl: './sign-in.html',
  styleUrl: './sign-in.css',
})
export class SignIn {
  private readonly auth = inject(Auth);
  private readonly router = inject(Router);

  readonly mode = signal<'sign-in' | 'register'>('sign-in');
  readonly email = signal('');
  readonly password = signal('');
  readonly busy = signal(false);
  readonly error = signal<string | null>(null);

  readonly registering = computed(() => this.mode() === 'register');

  /** Mirrors the backend's minimum so the failure is caught before a round trip. */
  readonly passwordTooShort = computed(
    () => this.password().length > 0 && this.password().length < 8,
  );

  canSubmit(): boolean {
    return (
      this.email().trim().length > 0 && this.password().length >= 8 && !this.busy()
    );
  }

  switchMode(): void {
    this.mode.update((current) => (current === 'sign-in' ? 'register' : 'sign-in'));
    this.error.set(null);
  }

  submit(): void {
    if (!this.canSubmit()) {
      return;
    }

    this.busy.set(true);
    this.error.set(null);

    const email = this.email().trim();
    const request = this.registering()
      ? this.auth.register(email, this.password())
      : this.auth.login(email, this.password());

    request.subscribe({
      next: () => {
        this.busy.set(false);
        this.router.navigate(['/']);
      },
      error: (e: Error) => {
        this.busy.set(false);
        this.error.set(e.message);
      },
    });
  }
}
