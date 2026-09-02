package com.graduation.server.controller;

import com.graduation.server.common.ApiResponse;
import com.graduation.server.controller.dto.LoginRequest;
import com.graduation.server.controller.dto.LoginResponse;
import com.graduation.server.controller.dto.ProfileRequest;
import com.graduation.server.controller.dto.ProfileResponse;
import com.graduation.server.controller.dto.ProfileUpdateRequest;
import com.graduation.server.controller.dto.RegisterRequest;
import com.graduation.server.controller.dto.RegisterResponse;
import com.graduation.server.service.AuthService;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/auth")
public class AuthController {

    private final AuthService authService;

    public AuthController(AuthService authService) {
        this.authService = authService;
    }

    @PostMapping("/login")
    public ApiResponse<LoginResponse> login(@RequestBody LoginRequest request) {
        try {
            return ApiResponse.ok(authService.login(request));
        } catch (IllegalArgumentException exception) {
            return ApiResponse.error(exception.getMessage());
        }
    }

    @PostMapping("/register")
    public ApiResponse<RegisterResponse> register(@RequestBody RegisterRequest request) {
        try {
            return ApiResponse.ok(authService.register(request));
        } catch (IllegalArgumentException exception) {
            return ApiResponse.error(exception.getMessage());
        }
    }

    @PostMapping("/profile")
    public ApiResponse<ProfileResponse> profile(@RequestBody ProfileRequest request) {
        try {
            return ApiResponse.ok(authService.profile(request));
        } catch (IllegalArgumentException exception) {
            return ApiResponse.error(exception.getMessage());
        }
    }

    @PostMapping("/profile/update")
    public ApiResponse<ProfileResponse> updateProfile(@RequestBody ProfileUpdateRequest request) {
        try {
            return ApiResponse.ok(authService.updateProfile(request));
        } catch (IllegalArgumentException exception) {
            return ApiResponse.error(exception.getMessage());
        }
    }
}
