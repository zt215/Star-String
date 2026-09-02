package com.graduation.server.repository;

import com.graduation.server.entity.User;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;

public interface UserRepository extends JpaRepository<User, Long> {

    Optional<User> findByUsername(String username);

    boolean existsByUsername(String username);

    boolean existsByPhone(String phone);

    boolean existsByEmail(String email);

    boolean existsByPhoneAndUsernameNot(String phone, String username);

    boolean existsByEmailAndUsernameNot(String email, String username);
}
