package com.graduation.server.controller.dto;

public record RegisterRequest(
        String username,
        String nickname,
        String phone,
        String email,
        String password
) {
}
