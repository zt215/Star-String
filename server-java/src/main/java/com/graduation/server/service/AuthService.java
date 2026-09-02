package com.graduation.server.service;

import com.graduation.server.controller.dto.LoginRequest;
import com.graduation.server.controller.dto.LoginResponse;
import com.graduation.server.controller.dto.ProfileRequest;
import com.graduation.server.controller.dto.ProfileResponse;
import com.graduation.server.controller.dto.ProfileUpdateRequest;
import com.graduation.server.controller.dto.RegisterRequest;
import com.graduation.server.controller.dto.RegisterResponse;
import com.graduation.server.entity.User;
import com.graduation.server.repository.UserRepository;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;

import java.util.UUID;

@Service
public class AuthService {

    private final UserRepository userRepository;
    private final PasswordEncoder passwordEncoder;

    public AuthService(UserRepository userRepository, PasswordEncoder passwordEncoder) {
        this.userRepository = userRepository;
        this.passwordEncoder = passwordEncoder;
    }

    public LoginResponse login(LoginRequest request) {
        if (request == null
                || request.username() == null
                || request.username().isBlank()
                || request.password() == null
                || request.password().isBlank()) {
            throw new IllegalArgumentException("用户名和密码不能为空");
        }

        User user = userRepository.findByUsername(request.username().trim())
                .filter(item -> passwordEncoder.matches(request.password(), item.getPasswordHash()))
                .orElseThrow(() -> new IllegalArgumentException("用户名或密码错误"));

        return new LoginResponse(user.getUsername(), UUID.randomUUID().toString());
    }

    public RegisterResponse register(RegisterRequest request) {
        validateRegisterRequest(request);

        String username = request.username().trim();
        String nickname = request.nickname().trim();
        String phone = request.phone().trim();
        String email = request.email().trim();

        if (userRepository.existsByUsername(username)) {
            throw new IllegalArgumentException("账户名已存在");
        }
        if (userRepository.existsByPhone(phone)) {
            throw new IllegalArgumentException("手机号已被使用");
        }
        if (userRepository.existsByEmail(email)) {
            throw new IllegalArgumentException("邮箱已被使用");
        }

        userRepository.save(
                new User(
                        username,
                        nickname,
                        phone,
                        email,
                        passwordEncoder.encode(request.password())
                )
        );
        return new RegisterResponse(username);
    }

    public ProfileResponse profile(ProfileRequest request) {
        if (request == null || request.username() == null || request.username().isBlank()) {
            throw new IllegalArgumentException("用户名不能为空");
        }
        User user = userRepository.findByUsername(request.username().trim())
                .orElseThrow(() -> new IllegalArgumentException("用户不存在"));
        return toProfile(user);
    }

    public ProfileResponse updateProfile(ProfileUpdateRequest request) {
        validateUpdateRequest(request);

        String username = request.username().trim();
        String nickname = request.nickname().trim();
        String phone = request.phone().trim();
        String email = request.email().trim();

        User user = userRepository.findByUsername(username)
                .orElseThrow(() -> new IllegalArgumentException("用户不存在"));
        if (userRepository.existsByPhoneAndUsernameNot(phone, username)) {
            throw new IllegalArgumentException("手机号已被使用");
        }
        if (userRepository.existsByEmailAndUsernameNot(email, username)) {
            throw new IllegalArgumentException("邮箱已被使用");
        }

        user.setNickname(nickname);
        user.setPhone(phone);
        user.setEmail(email);
        userRepository.save(user);
        return toProfile(user);
    }

    private ProfileResponse toProfile(User user) {
        return new ProfileResponse(
                user.getUsername(),
                user.getNickname(),
                user.getPhone(),
                user.getEmail()
        );
    }

    private void validateUpdateRequest(ProfileUpdateRequest request) {
        if (request == null) {
            throw new IllegalArgumentException("个人信息不能为空");
        }
        if (request.username() == null || request.username().isBlank()) {
            throw new IllegalArgumentException("用户名不能为空");
        }
        if (request.nickname() == null || request.nickname().isBlank()) {
            throw new IllegalArgumentException("昵称不能为空");
        }
        if (request.phone() == null || !request.phone().trim().matches("[0-9+\\-]{6,20}")) {
            throw new IllegalArgumentException("手机号格式不正确");
        }
        if (request.email() == null || !request.email().trim().matches("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$")) {
            throw new IllegalArgumentException("邮箱格式不正确");
        }
    }

    private void validateRegisterRequest(RegisterRequest request) {
        if (request == null) {
            throw new IllegalArgumentException("注册信息不能为空");
        }
        if (isBlank(request.username()) || request.username().trim().length() < 3) {
            throw new IllegalArgumentException("账户名至少3个字符");
        }
        if (isBlank(request.nickname())) {
            throw new IllegalArgumentException("昵称不能为空");
        }
        if (isBlank(request.phone()) || !request.phone().trim().matches("[0-9+\\-]{6,20}")) {
            throw new IllegalArgumentException("手机号格式不正确");
        }
        if (isBlank(request.email()) || !request.email().trim().matches("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$")) {
            throw new IllegalArgumentException("邮箱格式不正确");
        }
        if (request.password() == null || request.password().length() < 6) {
            throw new IllegalArgumentException("密码至少6位");
        }
    }

    private boolean isBlank(String value) {
        return value == null || value.isBlank();
    }
}
